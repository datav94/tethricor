"""Entry-point discovery for third-party provider packages.

A provider package (e.g. `tethricor-sandbox-microsandbox`) registers itself via Python entry
points, so new harnesses / sandboxes / model routers become available without editing
core:

    [project.entry-points."tethricor.sandboxes"]
    microsandbox = "tethricor_sandbox_microsandbox:make_provider"

Conventions for what an entry point must load to:
  - tethricor.sandboxes  -> a SandboxProvider factory  `(*, base_url, client, **kw) -> SandboxProvider`
  - tethricor.harnesses  -> a HarnessAdapter instance
  - tethricor.models     -> a ModelRouter instance
"""
from __future__ import annotations

from importlib import metadata
from typing import Iterable

from tethricor_runtime import adapters, model, registry

GROUP_SANDBOXES = "tethricor.sandboxes"
GROUP_HARNESSES = "tethricor.harnesses"
GROUP_MODELS = "tethricor.models"


def _entry_points(group: str) -> Iterable[metadata.EntryPoint]:
    eps = metadata.entry_points()
    # Python 3.10+: EntryPoints.select; older mapping API falls back to .get.
    if hasattr(eps, "select"):
        return eps.select(group=group)
    return eps.get(group, [])  # type: ignore[attr-defined]


def load_plugins() -> None:
    """Discover and register all installed provider plugins (idempotent)."""
    for ep in _entry_points(GROUP_SANDBOXES):
        registry.register_sandbox(ep.name, ep.load())
    for ep in _entry_points(GROUP_HARNESSES):
        adapters.register_harness(ep.name, ep.load())
    for ep in _entry_points(GROUP_MODELS):
        model.register_router(ep.name, ep.load())
