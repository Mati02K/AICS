# ---------- Minimal runbooks (need to add more here) ----------
RUNBOOKS = [
    {
        "id": "rb.crashloop",
        "title": "Pod CrashLoopBackOff",
        "signals": {
            "k8s.reason": "CrashLoopBackOff",
            "logs.contains_any": ["ModuleNotFoundError", "back-off restarting failed container"]
        },
        "steps": [
            {"action": "restart_service", "params": {"reason": "crashloop"}}
        ],
        "verify": [
            {"kind": "http", "url": "http://{service}.ops.svc.cluster.local/health", "expect_code": 200}
        ],
        "guardrails": {"max_actions": 1}
    },
    {
        "id": "rb.redis.down",
        "title": "Redis unreachable/errors",
        "signals": {
            "logs.contains_any": ["redis error", "connectionerror", "timeout"]
        },
        "steps": [
            {"action": "patch_env", "params": {"env": {"REDIS_SOCKET_TIMEOUT_MS": "800"}}}
        ],
        "verify": [{"kind": "metric_hint", "name": "redis errors decreased"}],
        "guardrails": {"max_actions": 1}
    },
    {
        "id": "rb.db.latency",
        "title": "Postgres latency/connection issues",
        "signals": {
            "logs.contains_any": ["connection refused", "postgres", "timeout"]
        },
        "steps": [
            {"action": "scale_service", "params": {"replicas": 3}}
        ],
        "verify": [{"kind": "metric_hint", "name": "p95 latency < 500ms"}],
        "guardrails": {"max_actions": 1}
    }
]
