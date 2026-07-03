"""The `Harness` facade — the plug-and-play entry point for the tethricor SDK.

Wraps the shim orchestrator + registries behind one small, typed surface. Harness,
model routing, and sandbox backend are all swappable by name (LangChain-style). This is
a thin adapter over `tethricor_runtime`; it holds no execution logic of its own (.cursorrules #6).
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Union

import yaml

from tethricor_runtime import registry
from tethricor_runtime.adapters import adapter_for
from tethricor_runtime.config import (
    DEFAULT_GATEWAY_URL,
    DEFAULT_MCP_URL,
    DEFAULT_RUNTIME_URL,
    Settings,
)
from tethricor_runtime.observability import Callbacks
from tethricor_runtime.orchestrator import print_event, run_task

from .types import Event, SandboxSession, TaskResult


class Harness:
    """A configured harness ready to run tasks against a sandbox provider."""

    def __init__(
        self,
        harness: str,
        *,
        sandbox: str,
        model: Optional[str] = None,
        source: Optional[str] = None,
        ref: Optional[str] = None,
        runtime_profile: Optional[str] = None,
        timeout_seconds: int = 600,
        skills: Optional[List[str]] = None,
        mcp_servers: Optional[List[str]] = None,
        runtime_url: str = DEFAULT_RUNTIME_URL,
        gateway_url: str = DEFAULT_GATEWAY_URL,
        mcp_url: str = DEFAULT_MCP_URL,
    ) -> None:
        profile = runtime_profile or adapter_for(harness).default_profile
        config = {
            "harness": {"type": harness},
            "model": {"routing_profile": model} if model else {},
            "skills": list(skills or []),
            "mcp": {"servers": list(mcp_servers or [])},
            "runtime": {"profile": profile, "timeout_seconds": timeout_seconds, "provider": sandbox},
            "source": {"repo_url": source, "ref": ref} if source else {},
        }
        self.settings = Settings(
            harness_type=harness,
            runtime_url=runtime_url,
            gateway_url=gateway_url,
            mcp_url=mcp_url,
            config=config,
        )

    # -- alternate constructors -------------------------------------------
    @classmethod
    def from_settings(cls, settings: Settings) -> "Harness":
        obj = cls.__new__(cls)
        obj.settings = settings
        return obj

    @classmethod
    def from_config(cls, config, **endpoints) -> "Harness":
        """Build from a harness.yaml path or an already-parsed dict."""
        if isinstance(config, (str, Path)):
            config = yaml.safe_load(Path(config).read_text(encoding="utf-8")) or {}
        settings = Settings(
            harness_type=config.get("harness", {}).get("type", ""),
            runtime_url=endpoints.get("runtime_url", DEFAULT_RUNTIME_URL),
            gateway_url=endpoints.get("gateway_url", DEFAULT_GATEWAY_URL),
            mcp_url=endpoints.get("mcp_url", DEFAULT_MCP_URL),
            config=config,
        )
        return cls.from_settings(settings)

    # -- API ---------------------------------------------------------------
    @property
    def sandbox(self) -> str:
        return self.settings.provider

    def run(
        self,
        task: Union[str, List[str], None] = None,
        *,
        argv: Optional[List[str]] = None,
        output_path: str = "changes.zip",
        stream: bool = False,
        callbacks: Optional[Callbacks] = None,
    ) -> TaskResult:
        """Run one task in the sandbox session; return the typed result.

        `task` may be a natural-language string (turned into the harness's launch command
        by the adapter) or an explicit argv list (forwarded verbatim). Execution always
        happens inside the sandbox session, never locally. `stream=True` prints events as
        they arrive; pass `callbacks` for structured observability hooks.
        """
        if isinstance(task, list):
            argv, task = task, None
        final_argv = adapter_for(self.settings.harness_type).run_argv(task=task, argv=argv)
        result = run_task(
            self.settings,
            final_argv,
            output_path=output_path,
            on_event=print_event if stream else None,
            callbacks=callbacks,
        )
        return TaskResult(
            session_id=result.session_id,
            exit_code=result.exit_code,
            artifact_path=result.artifact_path,
            events=[Event.from_dict(e) for e in result.events],
        )

    def open_session(self) -> SandboxSession:
        """Lower-level: create a raw sandbox session (caller manages its lifecycle)."""
        provider = registry.get_sandbox_provider(self.settings.provider, base_url=self.settings.runtime_url)
        try:
            raw = provider.create_session(
                self.settings.profile or adapter_for(self.settings.harness_type).default_profile,
                ttl_seconds=self.settings.timeout_seconds + 300,
                repo_url=self.settings.repo_url or None,
                ref=self.settings.ref or None,
            )
            return SandboxSession.from_dict(raw)
        finally:
            provider.close()
