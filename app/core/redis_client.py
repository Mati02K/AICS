import os, redis, time, uuid
import time as t

class RedisClient:
    def __init__(self, logger, metrics):
        self.log = logger
        self.metrics = metrics
        host = os.getenv("REDIS_HOST","localhost")
        port = int(os.getenv("REDIS_PORT","6379"))
        db   = int(os.getenv("REDIS_DB","0"))
        self.r = redis.Redis(
            host=host, port=port, db=db, decode_responses=True,
            socket_connect_timeout=0.2, socket_timeout=0.3
        )

    def ping(self):
        t0 = t.time()
        try:
            ok = self.r.ping()
            self.metrics.REDIS_LAT.labels("ping").observe(t.time()-t0)
            self.metrics.REDIS_OPS.labels("ping","ok").inc()
            return ok
        except redis.exceptions.RedisError as e:
            self.metrics.REDIS_OPS.labels("ping","error").inc()
            self.log.error(route="/health", msg="redis error", err=str(e))
            return False

    def stock_key(self, item_id: str) -> str:
        return f"stock:{item_id}"

    def get_stock_cached(self, item_id: str):
        t0 = t.time()
        try:
            v = self.r.get(self.stock_key(item_id))
            self.metrics.REDIS_LAT.labels("get_stock").observe(t.time()-t0)
            self.metrics.REDIS_OPS.labels("get_stock","ok").inc()
            return int(v) if v is not None else None
        except redis.exceptions.RedisError as e:
            self.metrics.REDIS_OPS.labels("get_stock","error").inc()
            self.log.error(route="/enquire", msg="redis get error", item_id=item_id, err=str(e))
            return None

    def set_stock_cached(self, item_id: str, qty: int, ttl_sec: int = 300):
        t0 = t.time()
        try:
            self.r.set(self.stock_key(item_id), qty, ex=ttl_sec)
            self.metrics.REDIS_LAT.labels("set_stock").observe(t.time()-t0)
            self.metrics.REDIS_OPS.labels("set_stock","ok").inc()
        except redis.exceptions.RedisError as e:
            self.metrics.REDIS_OPS.labels("set_stock","error").inc()
            self.log.error(route="/enquire", msg="redis set error", item_id=item_id, err=str(e))

    def decr_stock_cached(self, item_id: str, by: int = 1):
        t0 = t.time()
        try:
            # if key missing, do nothing; DB is source of truth
            if self.r.exists(self.stock_key(item_id)):
                self.r.decrby(self.stock_key(item_id), by)
            self.metrics.REDIS_LAT.labels("decr_stock").observe(t.time()-t0)
            self.metrics.REDIS_OPS.labels("decr_stock","ok").inc()
        except redis.exceptions.RedisError as e:
            self.metrics.REDIS_OPS.labels("decr_stock","error").inc()
            self.log.error(route="/checkout", msg="redis decr error", item_id=item_id, err=str(e))

    '''
    * This is done to avoid single user over buying mechanism.
    * simple per-user per-item lock (rate-limit / duplicate prevention) ----------
    * Prevents a single user from racing multiple concurrent purchases of the same item.
    * Lock auto-expires to avoid deadlocks if a request dies mid-flight.
    '''
    def acquire_user_item_lock(self, user_id: str, item_id: str, ttl_sec: int = 5):
        lock_key = f"lock:{user_id}:{item_id}"
        token = str(uuid.uuid4())
        try:
            ok = self.r.set(lock_key, token, nx=True, ex=ttl_sec)
            return (ok is True), lock_key, token
        except redis.exceptions.RedisError:
            return (False, lock_key, None)

    def release_lock(self, lock_key: str, token: str):
        # best-effort release; compare token to avoid releasing other caller's lock
        try:
            pipe = self.r.pipeline()
            while True:
                try:
                    pipe.watch(lock_key)
                    cur = pipe.get(lock_key)
                    if cur == token:
                        pipe.multi()
                        pipe.delete(lock_key)
                        pipe.execute()
                    pipe.unwatch()
                    break
                except redis.exceptions.WatchError:
                    continue
        except redis.exceptions.RedisError:
            pass
