"""Local-only utility: route the harness SDK straight at Azure OpenAI.

This is a **developer convenience for when you do not have an AgentGateway yet**. In
production, all LLM traffic MUST flow through AgentGateway (`.cursorrules` #2); this
module is deliberately kept out of the core routing path and only takes effect when you
explicitly opt in via :func:`use_direct_azure_openai` (or construct
:class:`AzureOpenAIRouter` and select it yourself).

It stays safe by construction:

* It is opt-in — the default model router is unchanged, so nothing routes to Azure
  unless you call the helper below.
* The CLI/webhook still strip ``model.direct_azure_openai`` for every non-``local``
  deployment target, so this cannot leak into ``aks``/``aci``/``job`` artifacts.
* The API key is never read from ``harness.yaml`` (the schema forbids it); it comes from
  an explicit argument or the ``AZURE_OPENAI_API_KEY`` environment variable.

Typical use::

    from tethricor import Harness, use_direct_azure_openai

    use_direct_azure_openai(
        endpoint="https://my-res.openai.azure.com",
        deployment="gpt-4o",
        api_key="...",            # or set AZURE_OPENAI_API_KEY
    )
    Harness("hermes", sandbox="remote-runtime", source="https://github.com/org/repo.git").run("do the thing")
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Optional

from tethricor_runtime.interfaces import ModelRouter
from tethricor_runtime.model import register_router

# Name this router registers under and that TETHRICOR_MODEL_ROUTER selects.
ROUTER_NAME = "direct-azure-openai"

# Conservative, widely-available Azure OpenAI GA API version used when none is given.
DEFAULT_API_VERSION = "2024-10-21"

# Environment variable the API key is read from when not passed explicitly.
API_KEY_ENV = "AZURE_OPENAI_API_KEY"


@dataclass(frozen=True)
class AzureOpenAIRouter(ModelRouter):
    """A :class:`ModelRouter` that points harnesses directly at Azure OpenAI.

    Bypasses AgentGateway entirely — intended only for local development before a
    gateway is available. It emits both the native Azure env (``AZURE_OPENAI_*``, used by
    the Azure OpenAI SDK / LiteLLM) and an OpenAI-compatible ``OPENAI_BASE_URL`` so a
    range of harnesses can pick it up.
    """

    endpoint: str
    deployment: str
    api_key: str
    api_version: str = DEFAULT_API_VERSION

    @property
    def resource_endpoint(self) -> str:
        return self.endpoint.rstrip("/")

    @property
    def base_url(self) -> str:
        return f"{self.resource_endpoint}/openai/deployments/{self.deployment}"

    def llm_env(self, gateway_url: str) -> Dict[str, str]:  # noqa: ARG002 - no gateway here
        base = self.base_url
        return {
            # OpenAI-compatible clients.
            "OPENAI_BASE_URL": f"{base}?api-version={self.api_version}",
            "OPENAI_API_BASE": f"{base}?api-version={self.api_version}",
            "OPENAI_API_TYPE": "azure",
            # Native Azure OpenAI SDK / LiteLLM clients.
            "AZURE_OPENAI_ENDPOINT": self.resource_endpoint,
            "AZURE_OPENAI_DEPLOYMENT": self.deployment,
            "AZURE_OPENAI_API_VERSION": self.api_version,
        }

    def secret_env(self) -> Dict[str, str]:
        # Survives the adapter's provider-key scrub (that is the whole point of the
        # escape hatch). Kept separate from llm_env so credentials never sit alongside
        # non-secret routing config.
        return {
            "AZURE_OPENAI_API_KEY": self.api_key,
            "OPENAI_API_KEY": self.api_key,
        }


def build_router(
    *,
    endpoint: str,
    deployment: str,
    api_key: Optional[str] = None,
    api_version: Optional[str] = None,
) -> AzureOpenAIRouter:
    """Construct an :class:`AzureOpenAIRouter`, sourcing the key from the environment.

    Raises ``ValueError`` if no API key is provided or found in ``AZURE_OPENAI_API_KEY``.
    """
    key = api_key or os.environ.get(API_KEY_ENV, "")
    if not key:
        raise ValueError(
            f"no Azure OpenAI API key: pass api_key=... or set ${API_KEY_ENV}"
        )
    return AzureOpenAIRouter(
        endpoint=endpoint,
        deployment=deployment,
        api_key=key,
        api_version=api_version or DEFAULT_API_VERSION,
    )


def build_router_from_config(
    direct: Dict[str, str], *, api_key: Optional[str] = None
) -> AzureOpenAIRouter:
    """Build a router from a ``harness.yaml`` ``model.direct_azure_openai`` block.

    The key is never taken from config (the schema forbids it); it comes from ``api_key``
    or ``$AZURE_OPENAI_API_KEY``.
    """
    return build_router(
        endpoint=direct["endpoint"],
        deployment=direct["deployment"],
        api_key=api_key,
        api_version=direct.get("api_version"),
    )


def use_direct_azure_openai(
    *,
    endpoint: str,
    deployment: str,
    api_key: Optional[str] = None,
    api_version: Optional[str] = None,
) -> AzureOpenAIRouter:
    """Register the direct-Azure router and make it the active model router.

    After calling this, any :class:`tethricor.Harness` run routes LLM traffic straight at
    Azure OpenAI instead of AgentGateway (local dev only). Returns the router so callers
    can inspect it. Call :func:`disable` to revert to the default gateway router.
    """
    router = build_router(
        endpoint=endpoint,
        deployment=deployment,
        api_key=api_key,
        api_version=api_version,
    )
    register_router(ROUTER_NAME, router)
    os.environ["TETHRICOR_MODEL_ROUTER"] = ROUTER_NAME
    return router


def disable() -> None:
    """Revert to the default (gateway) model router selection."""
    if os.environ.get("TETHRICOR_MODEL_ROUTER") == ROUTER_NAME:
        del os.environ["TETHRICOR_MODEL_ROUTER"]
