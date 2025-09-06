import os, json, requests
import ollama 
import re
from prompt import SYSTEM_PROMPT
from runbook import RUNBOOKS

SERVER = os.getenv("MCP_SERVER", "http://127.0.0.1:8055")

# ---------- Sample logs (for testing) ----------
# SAMPLE_LOGS = {
#     "api": [
#         "CrashLoopBackOff",
#         "ModuleNotFoundError: No module named 'core'",
#         "back-off restarting failed container"
#     ],
#     "redis": [
#         "redis error: timeout",
#         "ConnectionError: timed out"
#     ],
#     "db": [
#         "db error: connection refused",
#         "timeout while connecting to postgres"
#     ],
# }


ALLOWED_TOOLS = {"restart_service", "scale_service", "patch_env", "get_logs"}

def scrape_metrics(url: str) -> dict[str, float]:
    """Fetch /metrics from a service and parse into {metric: value}."""
    try:
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        metrics = {}
        for line in r.text.splitlines():
            if line.startswith("#"): 
                continue
            parts = line.split()
            if len(parts) == 2:
                name, val = parts
                try:
                    metrics[name] = float(val)
                except ValueError:
                    pass
        return metrics
    except Exception as e:
        print("metrics scrape error:", e)
        return {}

def collect_logs_from_metrics(service: str, port: int = 80) -> list[str]:
    url = f"http://{service}:{port}/metrics"
    
    metrics = scrape_metrics(url)
    logs = []
    
    # Add lightweight hints for the LLM
    for k, v in metrics.items():
        if "http_requests_total" in k and v > 0:
            logs.append(f"metric:{k} value={int(v)}")
        if "redis_ops_total" in k and v > 0:
            logs.append(f"metric:{k} value={int(v)}")
        if "db_ops_total" in k and v > 0:
            logs.append(f"metric:{k} value={int(v)}")
    
    return logs


def _extract_json(text: str) -> dict | None:
    # Try strict JSON block extraction
    m = re.search(r"\{(?:.|\n)*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None

def llm_choose_action(service: str, logs: list[str]) -> dict:
    payload = {"service": service, "logs": logs, "runbooks": RUNBOOKS}

    def _ask(prompt_suffix: str = "") -> dict | None:
        resp = ollama.chat(
            model=os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b-instruct"),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT + prompt_suffix},
                {"role": "user", "content": json.dumps(payload, indent=2)},
            ],
            # keep memory small; force json-only output
            options={"temperature": 0, "num_ctx": 512, "num_predict": 128, "format": "json"},
        )
        text = resp["message"]["content"].strip()
        # First try direct JSON
        try:
            return json.loads(text)
        except Exception:
            # Then try extracting the first JSON object
            return _extract_json(text)

    plan = None
    # try once with JSON format
    plan = _ask()
    if plan is None:
        # second attempt with an even stricter suffix
        plan = _ask("\nReturn ONLY the JSON object. If unsure, choose get_logs.")
    if plan is None:
        # final fallback: safe default so the loop doesn't die
        return {"runbook_id": "fallback.get_logs", "tool": "get_logs", "params": {"service": service}}

    # Minimal validation & fixes
    if not isinstance(plan, dict):
        return {"runbook_id": "fallback.get_logs", "tool": "get_logs", "params": {"service": service}}

    tool = plan.get("tool")
    if tool not in ALLOWED_TOOLS:
        tool = "get_logs"
    params = plan.get("params") or {}
    params["service"] = service  # ensure present
    plan["tool"] = tool
    plan["params"] = params

    # (optional) ensure tool exists in chosen runbook's steps
    rb_id = plan.get("runbook_id")
    if rb_id:
        matched = next((rb for rb in RUNBOOKS if rb.get("id") == rb_id), None)
        if matched:
            allowed = {s.get("action") for s in (matched.get("steps") or [])}
            if tool not in allowed:
                plan["tool"] = "get_logs"

    return plan

def call_tool(tool: str, params: dict, logs: list[str]):
    body = dict(params)
    body["logs"] = logs
    r = requests.post(f"{SERVER}/tool/{tool}", json=body, timeout=10)
    r.raise_for_status()
    return r.json()

def main():
    
    service = os.getenv("SERVICE", "api")

    # scrape metrics directly from service
    logs = collect_logs_from_metrics(service, port=80)
    print(f"Logs from metrics {logs}")
    if not logs:
        # logs = SAMPLE_LOGS.get(service, [])
        print("== (ERROR metrics empty/unreachable) ==")

    echo = call_tool("get_logs", {"service": service}, logs)
    print("== get_logs:", echo)

    plan = llm_choose_action(service, logs)
    print("== plan:", plan)

    result = call_tool(plan["tool"], plan["params"], logs)
    print("== exec:", result)

if __name__ == "__main__":
    main()
