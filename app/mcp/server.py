from typing import List, Optional, Dict, Any
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn, os, time, datetime
from kubernetes import client, config
from kubernetes.client import AppsV1Api, CoreV1Api

# Try in-cluster, fall back to local kubeconfig for dev
try:
    config.load_incluster_config()
except Exception:
    config.load_kube_config()

apps_api: AppsV1Api = client.AppsV1Api()
core_api: CoreV1Api = client.CoreV1Api()
NAMESPACE = os.getenv("NAMESPACE", "ops")

app = FastAPI(title="MCP Demo Tools (K8s-enabled)")

# ---------- Request/Response Models ----------
class GetLogsReq(BaseModel):
    service: str
    logs: List[str]

class RestartServiceReq(BaseModel):
    service: str
    reason: Optional[str] = None
    logs: List[str]

class ScaleReq(BaseModel):
    service: str
    replicas: int
    logs: List[str]

class PatchEnvReq(BaseModel):
    service: str
    env: Dict[str, Any]
    logs: List[str]

class ToolResult(BaseModel):
    ok: bool
    tool: str
    detail: str
    meta: Dict[str, Any] = {}

# ---------- Helpers ----------
def _restart_deployment(deploy: str):
    # Rollout restart = patch an annotation with a fresh timestamp
    ts = datetime.datetime.utcnow().isoformat() + "Z"
    patch = {
        "spec": {
            "template": {
                "metadata": {
                    "annotations": {
                        "kubectl.kubernetes.io/restartedAt": ts
                    }
                }
            }
        }
    }
    apps_api.patch_namespaced_deployment(
        name=deploy, namespace=NAMESPACE, body=patch
    )
    return ts

def _scale_deployment(deploy: str, replicas: int):
    patch = {"spec": {"replicas": int(replicas)}}
    apps_api.patch_namespaced_deployment(
        name=deploy, namespace=NAMESPACE, body=patch
    )

def _patch_env_on_deployment(deploy: str, env: Dict[str, Any]):
    # Merge/replace env on the FIRST container in the pod template
    # (keep this simple; your deployments have a single container)
    # Build env array [{name:..., value:...}, ...]
    env_list = [{"name": k, "value": str(v)} for k, v in env.items()]

    # We need to preserve existing env vars and merge keys; read current spec
    dep = apps_api.read_namespaced_deployment(name=deploy, namespace=NAMESPACE)
    containers = dep.spec.template.spec.containers
    if not containers:
        raise RuntimeError("Deployment has no containers")
    current = containers[0].env or []
    cur_map = {e.name: e.value for e in current}

    # merge
    cur_map.update({e["name"]: e["value"] for e in env_list})
    merged_env = [{"name": k, "value": v} for k, v in cur_map.items()]

    patch = {
        "spec": {
            "template": {
                "spec": {
                    "containers": [
                        {
                            "name": containers[0].name,
                            "env": merged_env
                        }
                    ]
                }
            }
        }
    }
    apps_api.patch_namespaced_deployment(
        name=deploy, namespace=NAMESPACE, body=patch
    )

# ---------- Tools (now with real actions) ----------

@app.post("/tool/get_logs", response_model=ToolResult)
def get_logs(req: GetLogsReq):
    return ToolResult(
        ok=True,
        tool="get_logs",
        detail=f"returned {len(req.logs)} log lines for service={req.service}",
        meta={"service": req.service, "logs": req.logs},
    )

@app.post("/tool/restart_service", response_model=ToolResult)
def restart_service(req: RestartServiceReq):
    # service name == deployment name
    ts = _restart_deployment(req.service)
    return ToolResult(
        ok=True,
        tool="restart_service",
        detail=f"rollout restarted service={req.service} at {ts}",
        meta={"service": req.service, "reason": req.reason or "unspecified", "timestamp": ts},
    )

@app.post("/tool/scale_service", response_model=ToolResult)
def scale_service(req: ScaleReq):
    _scale_deployment(req.service, req.replicas)
    return ToolResult(
        ok=True,
        tool="scale_service",
        detail=f"scaled service={req.service} to replicas={req.replicas}",
        meta={"service": req.service, "replicas": req.replicas},
    )

@app.post("/tool/patch_env", response_model=ToolResult)
def patch_env(req: PatchEnvReq):
    _patch_env_on_deployment(req.service, req.env)
    # Best practice: restart so new env is picked up
    ts = _restart_deployment(req.service)
    return ToolResult(
        ok=True,
        tool="patch_env",
        detail=f"patched env and restarted service={req.service}",
        meta={"service": req.service, "env": req.env, "timestamp": ts},
    )

@app.get("/healthz")
def healthz():
    return {"ok": True, "ns": NAMESPACE}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8055)
