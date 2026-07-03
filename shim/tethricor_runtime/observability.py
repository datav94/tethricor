"""Observability hooks for the task lifecycle (OTel/LangSmith-style callbacks).

A single, no-op-by-default `Callbacks` surface the orchestrator fires at each lifecycle
point. Enterprise deployments subclass it to emit spans/metrics/logs (delegating to
AgentGateway/OTel); the SDK accepts an instance so callers can trace runs. Kept tiny and
side-effect-free by default so nothing changes unless a callback is supplied.
"""
from __future__ import annotations

from typing import List, Optional


class Callbacks:
    """Lifecycle hooks; override any subset. All methods are no-ops by default."""

    def on_session_start(self, session: dict) -> None: ...

    def on_exec_start(self, exec_rec: dict, argv: List[str]) -> None: ...

    def on_event(self, event: dict) -> None: ...

    def on_artifact(self, path: str) -> None: ...

    def on_session_end(self, session_id: str, *, exit_code: Optional[int]) -> None: ...


class _EventOnly(Callbacks):
    """Adapts a bare `on_event` callable to the Callbacks surface (back-compat sugar)."""

    def __init__(self, fn) -> None:
        self._fn = fn

    def on_event(self, event: dict) -> None:
        self._fn(event)
