"""Model routing providers.

v1 routing is simple: point the harness's OpenAI-compatible client at AgentGateway
(.cursorrules #2). This centralizes the base-URL env so adapters don't each hardcode it,
and gives Phase 8/9 a seam to add richer routers (model aliases, per-provider routing)
without touching adapters.
"""
from __future__ import annotations

import os
from typing import Dict, List

from .interfaces import ModelRouter

GATEWAY_ROUTER = "gateway"


class GatewayRouter(ModelRouter):
    """Routes all LLM traffic through AgentGateway's OpenAI-compatible surface."""

    def llm_env(self, gateway_url: str) -> Dict[str, str]:
        return {
            "OPENAI_BASE_URL": gateway_url,
            "OPENAI_API_BASE": gateway_url,
            "ANTHROPIC_BASE_URL": gateway_url,
        }


_ROUTERS: Dict[str, ModelRouter] = {GATEWAY_ROUTER: GatewayRouter()}


def register_router(name: str, router: ModelRouter) -> None:
    """Register (or override) a model router. Used by plugin discovery."""
    _ROUTERS[name] = router


def available_routers() -> List[str]:
    return sorted(_ROUTERS)


def get_router(name: str) -> ModelRouter:
    try:
        return _ROUTERS[name]
    except KeyError as exc:
        raise KeyError(f"unknown model router {name!r}; available: {available_routers()}") from exc


def default_router() -> ModelRouter:
    """The active router — selectable via `TETHRICOR_MODEL_ROUTER` (defaults to gateway)."""
    return _ROUTERS.get(os.environ.get("TETHRICOR_MODEL_ROUTER", GATEWAY_ROUTER), _ROUTERS[GATEWAY_ROUTER])
