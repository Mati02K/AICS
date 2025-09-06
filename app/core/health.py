class HealthChecker:
    def __init__(self, logger, metrics, redis_client, db):
        self.log = logger
        self.metrics = metrics
        self.redis = redis_client
        self.db = db

    def liveness(self):
        # Right now I think just hitting this would be enough
        return {"ok": True}

    def readiness(self):
        r_ok = self.redis.ping()
        d_ok = self.db.health()
        ok = bool(r_ok and d_ok)
        return {"ok": ok, "redis": "up" if r_ok else "down", "db": "up" if d_ok else "down"}, (200 if ok else 503)
