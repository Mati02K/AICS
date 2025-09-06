from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

class Metrics:
    def __init__(self):
        self.REQS = Counter("http_requests_total","Total HTTP requests",["route","code"])
        self.LAT  = Histogram("http_request_latency_seconds","Request latency (s)",["route"])
        self.REDIS_OPS = Counter("redis_ops_total","Redis operations",["op","result"])  # ok|timeout|error
        self.REDIS_LAT = Histogram("redis_op_latency_seconds","Redis op latency (s)",["op"])
        self.DB_OPS = Counter("db_ops_total","DB operations",["op","result"])  # ok|error
        self.DB_LAT = Histogram("db_op_latency_seconds","DB op latency (s)",["op"])

    @staticmethod
    def expose():
        return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}
