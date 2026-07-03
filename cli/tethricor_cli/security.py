"""Platform-enforced security invariants applied at generation time.

The developer declares intent in harness.yaml; these helpers enforce the guarantees
the developer cannot opt out of (DESIGN_NOTES §4, §8, and .cursorrules #1/#2).
"""
from __future__ import annotations

import copy
from typing import Dict, List

# Egress default-deny allowlist: the only destinations a hardened harness may reach.
EGRESS_ALLOWLIST: List[str] = ["agentgateway", "agent-runtime"]

LOCAL_TARGET = "local"


def sanitize_for_target(config: dict, target: str) -> dict:
    """Return a copy of the config with target-appropriate security applied.

    - Strips the local-only `model.direct_azure_openai` escape hatch for any
      non-local target (it must never reach a deployed environment).
    """
    cfg = copy.deepcopy(config)
    if target != LOCAL_TARGET:
        model = cfg.get("model")
        if isinstance(model, dict):
            model.pop("direct_azure_openai", None)
    return cfg


def pod_security_context() -> Dict[str, object]:
    """Locked-down container security context for injected sidecars."""
    return {
        "runAsNonRoot": True,
        "runAsUser": 1001,
        "readOnlyRootFilesystem": True,
        "allowPrivilegeEscalation": False,
        "capabilities": {"drop": ["ALL"]},
    }
