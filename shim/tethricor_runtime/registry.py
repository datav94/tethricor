"""Sandbox provider registry.

The genuinely new plug-and-play axis in Framework v0. Providers register a factory by
name; the orchestrator resolves one from `runtime.provider`. There is no "blessed"
default provider — `remote-runtime` (a generic REST/SSE client implementing the sandbox
execution contract) works against *any* compatible service: something you self-host,
a vendor's, or the bundled `mock_sandbox.py` test double for local dev. Stronger-isolation
options (`microsandbox`, `e2b`, or your own) register as separate installable packages.
`tethricor.discovery` populates this from Python entry points so third-party provider
packages register without editing core. The harness-adapter and model-router registries
live in `adapters.py` / `model.py`, so they are not duplicated here.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

import httpx

from .interfaces import SandboxProvider
from .runtime_client import RuntimeClient

REMOTE_RUNTIME = "remote-runtime"
# Deprecated alias, kept so configs/scripts written against the earlier name keep
# working. New configs should use REMOTE_RUNTIME.
ENTERPRISE_RUNTIME = "enterprise-runtime"

SandboxFactory = Callable[..., SandboxProvider]

_FACTORIES: Dict[str, SandboxFactory] = {}


def register_sandbox(name: str, factory: SandboxFactory) -> None:
    _FACTORIES[name] = factory


def available_sandboxes() -> List[str]:
    return sorted(_FACTORIES)


def get_sandbox_provider(
    name: str,
    *,
    base_url: str = "",
    client: Optional[httpx.Client] = None,
    **kwargs,
) -> SandboxProvider:
    try:
        factory = _FACTORIES[name]
    except KeyError as exc:
        raise KeyError(f"unknown sandbox provider {name!r}; available: {available_sandboxes()}") from exc
    return factory(base_url=base_url, client=client, **kwargs)


def _remote_runtime_factory(*, base_url: str = "", client: Optional[httpx.Client] = None, **_) -> SandboxProvider:
    return RuntimeClient(base_url, client=client)


register_sandbox(REMOTE_RUNTIME, _remote_runtime_factory)
register_sandbox(ENTERPRISE_RUNTIME, _remote_runtime_factory)  # deprecated alias, same factory
