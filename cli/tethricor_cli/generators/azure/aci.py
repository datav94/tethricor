"""`--target aci`: Azure Container Instances container group (generation-time injection).

Azure-specific, opt-in target -- unlike `aks`/`k8s`, ACI has no cloud-neutral
equivalent generator in this project (no fabricated AWS/GCP stand-in), so this stays
honestly Azure-only. Use `--target k8s` for a cloud-neutral deployment.

No admission webhook on ACI, so the CLI composes the sidecar directly into the group.
Execution is forwarded to the central sandbox runtime (ACI's own exec is not used).
"""
from __future__ import annotations

from typing import Dict

from .._common import dump_yaml, sidecar_env

# In prod these resolve to the central platform endpoints.
_RUNTIME_URL = "http://agent-runtime.internal:8080"
_MCP_URL = "http://agentgateway.internal/mcp"
_GATEWAY_URL = "http://agentgateway.internal"


def generate(config: dict, image: str) -> Dict[str, str]:
    env = sidecar_env(config, runtime_url=_RUNTIME_URL, mcp_url=_MCP_URL, gateway_url=_GATEWAY_URL)
    name = f"tethricor-{config['harness']['type']}"

    group = {
        "apiVersion": "2021-10-01",
        "location": "westeurope",
        "name": name,
        "type": "Microsoft.ContainerInstance/containerGroups",
        "identity": {"type": "UserAssigned", "userAssignedIdentities": {"REPLACE_WORKLOAD_IDENTITY": {}}},
        "properties": {
            "osType": "Linux",
            "restartPolicy": "Never",
            "containers": [
                {
                    "name": "app",
                    "properties": {
                        "image": "REPLACE_WITH_YOUR_APP_IMAGE",
                        "resources": {"requests": {"cpu": 1, "memoryInGB": 1}},
                    },
                },
                {
                    "name": "harness-sidecar",
                    "properties": {
                        "image": image,
                        "environmentVariables": [{"name": k, "value": v} for k, v in env.items()],
                        "resources": {"requests": {"cpu": 1, "memoryInGB": 2}},
                    },
                },
            ],
        },
    }

    return {"aci-container-group.yaml": dump_yaml(group)}
