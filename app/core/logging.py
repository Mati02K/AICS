import sys, json, time

class JsonLogger:
    def __init__(self, service="api"):
        self.service = service

    def log(self, level: str, **kv):
        kv.setdefault("service", self.service)
        kv.setdefault("level", level.upper())
        kv.setdefault("ts", time.time())
        line = json.dumps(kv, ensure_ascii=False)
        sys.stdout.write(line + "\n")
        sys.stdout.flush()

    def info(self, **kv):  self.log("INFO", **kv)
    def warn(self, **kv):  self.log("WARN", **kv)
    def error(self, **kv): self.log("ERROR", **kv)
