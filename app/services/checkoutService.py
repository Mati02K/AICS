import time
import re

class CheckoutService:
    def __init__(self, logger, metrics, redis_client, db):
        self.log = logger
        self.metrics = metrics
        self.redis = redis_client
        self.db = db

    @staticmethod
    def _parse_item_id(item_id: str) -> int:
        """
        Accepts 'I001' or '1' → returns 1
        """
        s = str(item_id).strip()
        if s.upper().startswith("I"):
            s = s[1:]
        s = s.lstrip("0") or "0"
        return int(s)

    def enquire(self, item_id: str):
        t0 = time.time()
        try:
            iid = self._parse_item_id(item_id)

            # 1) try Redis cache
            cached = self.redis.get_stock_cached(iid)
            if cached is not None:
                in_stock = cached > 0
                self.metrics.LAT.labels("/enquire").observe(time.time()-t0)
                self.metrics.REQS.labels("/enquire","200").inc()
                self.log.info(route=f"/enquire/{item_id}", status=200, msg="cache", stock=cached)
                return {"item_id": item_id, "in_stock": in_stock, "stock": cached, "source": "cache"}, 200

            # 2) fallback to DB
            item = self.db.get_item(iid)
            if not item:
                self.metrics.LAT.labels("/enquire").observe(time.time()-t0)
                self.metrics.REQS.labels("/enquire","404").inc()
                return {"error": "item not found"}, 404

            stock = int(item["qty"])
            
            # 3) set cache (best-effort)
            self.redis.set_stock_cached(iid, stock, ttl_sec=300)

            self.metrics.LAT.labels("/enquire").observe(time.time()-t0)
            self.metrics.REQS.labels("/enquire","200").inc()
            self.log.info(route=f"/enquire/{item_id}", status=200, msg="db", stock=stock)
            return {
                "item_id": item_id,
                "in_stock": stock > 0,
                "stock": stock,
                "source": "db",
                "name": item["name"],
                "price_cents": int(item["price_cents"])
            }, 200
        except Exception as e:
            self.metrics.LAT.labels("/enquire").observe(time.time()-t0)
            self.metrics.REQS.labels("/enquire","502").inc()
            self.log.error(route=f"/enquire/{item_id}", status=502, msg="dependency error", err=str(e))
            return {"ok": False, "error": "dependency error"}, 502

    def checkout(self, user_id: str, item_id: str, qty: int):
        t0 = time.time()
        route = f"/checkout/{item_id}/{qty if qty is not None else ''}".rstrip("/")
        if qty is None or qty <= 0 or not user_id:
            self.metrics.LAT.labels("/checkout").observe(time.time()-t0)
            self.metrics.REQS.labels("/checkout","400").inc()
            self.log.warn(route=route, status=400, msg="bad request", user=user_id)
            return {"error":"bad request"}, 400

        iid = self._parse_item_id(item_id)

        # Per-user per-item lock (5s)
        locked, lock_key, token = self.redis.acquire_user_item_lock(user_id, item_id, ttl_sec=5)
        if not locked:
            self.metrics.LAT.labels("/checkout").observe(time.time()-t0)
            self.metrics.REQS.labels("/checkout","429").inc()
            self.log.warn(route=route, status=429, msg="rate limited", user=user_id)
            return {"error":"rate limited, try again in a few seconds"}, 429

        try:
            # consult cache to short-circuit obvious OOS
            cached = self.redis.get_stock_cached(iid)
            if cached is not None and cached < qty:
                self.metrics.LAT.labels("/checkout").observe(time.time()-t0)
                self.metrics.REQS.labels("/checkout","409").inc()
                self.log.warn(route=route, status=409, msg="out of stock (cache)", user=user_id, stock=cached)
                return {"ok": False, "error":"out of stock", "stock_cached": cached}, 409

            # DB purchase (atomic)
            result = self.db.purchase(iid, qty)
            if not result:
                self.metrics.LAT.labels("/checkout").observe(time.time()-t0)
                self.metrics.REQS.labels("/checkout","409").inc()
                self.log.warn(route=route, status=409, msg="out of stock (db)", user=user_id)
                return {"ok": False, "error":"out of stock"}, 409

            # Update cache (best-effort)
            self.redis.decr_stock_cached(iid, by=qty)

            self.metrics.LAT.labels("/checkout").observe(time.time()-t0)
            self.metrics.REQS.labels("/checkout","200").inc()
            self.log.info(route=route, status=200, msg="purchase ok", user=user_id, order=result["order"])
            return {"ok": True, "order": result["order"], "new_qty": result["new_qty"]}, 200

        except Exception as e:
            self.metrics.LAT.labels("/checkout").observe(time.time()-t0)
            self.metrics.REQS.labels("/checkout","502").inc()
            self.log.error(route=route, status=502, msg="dependency error", user=user_id, err=str(e))
            return {"ok": False, "error":"dependency error"}, 502
        finally:
            if token:
                self.redis.release_lock(lock_key, token)
