"""`--target job`: Azure Container Apps Job (generation-time injection).

Azure-specific, opt-in target -- unlike `aks`/`k8s`, Container Apps Jobs have no
cloud-neutral equivalent generator in this project (no fabricated AWS/GCP stand-in),
so this stays honestly Azure-only. Use `--target k8s` for a cloud-neutral deployment.

Batch/one-shot execution of a harness task. Sidecar + app composed into the job
template; execution forwarded to the central sandbox runtime.
"""
from __future__ import annotations

from typing import Dict

from .._common import dump_yaml, sidecar_env

_RUNTIME_URL = "http://agent-runtime.internal:8080"
_MCP_URL = "http://agentgateway.internal/mcp"
_GATEWAY_URL = "http://agentgateway.internal"


def generate(config: dict, image: str) -> Dict[str, str]:
    env = sidecar_env(config, runtime_url=_RUNTIME_URL, mcp_url=_MCP_URL, gateway_url=_GATEWAY_URL)
    name = f"tethricor-{config['harness']['type']}-job"

    job = {
        "apiVersion": "2024-03-01",
        "type": "Microsoft.App/jobs",
        "name": name,
        "location": "westeurope",
        "identity": {"type": "UserAssigned", "userAssignedIdentities": {"REPLACE_WORKLOAD_IDENTITY": {}}},
        "properties": {
            "configuration": {
                "triggerType": "Manual",
                "replicaTimeout": config.get("runtime", {}).get("timeout_seconds", 600),
                "replicaRetryLimit": 0,
            },
            "template": {
                "containers": [
                    {
                        "name": "harness-sidecar",
                        "image": image,
                        "env": [{"name": k, "value": v} for k, v in env.items()],
                        "resources": {"cpu": 1.0, "memory": "2Gi"},
                    }
                ]
            },
        },
    }

    return {"aca-job.yaml": dump_yaml(job)}
