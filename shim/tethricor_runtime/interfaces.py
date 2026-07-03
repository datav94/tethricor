"""Stable provider interfaces for the Tethricor framework (plug-and-play axes).

These ABCs define the three swappable axes (see docs/agent_context/FRAMEWORK_EVOLUTION.md
§4): SandboxProvider, HarnessAdapter, ModelRouter. The concrete implementations that
ship today (RuntimeClient, Adapter, GatewayRouter) are the reference implementations —
this module only formalizes the contract they already satisfy, so nothing changes at
runtime. The sandbox error envelope lives here because it is part of the SandboxProvider
contract (any provider must raise these), and is re-exported from runtime_client for
backwards compatibility.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Iterator, List, Optional


# --- sandbox error envelope (part of the SandboxProvider contract) ---------
class RuntimeError_(Exception):
    """Non-success response carrying the runtime's error envelope."""

    def __init__(self, code: str, message: str, status: int) -> None:
        super().__init__(f"[{status}] {code}: {message}")
        self.code = code
        self.message = message
        self.status = status


class SessionExpired(RuntimeError_):
    """Raised on HTTP 410 (session_expired)."""


class SandboxProvider(ABC):
    """A backend that runs forwarded commands in an isolated session.

    Mirrors api-spec/sandbox-execution-contract.yaml: sessions -> async exec (202) ->
    SSE events (stdout|stderr|exit|error) -> artifact download -> delete. Implementations
    MUST forward execution to an isolated backend over REST/WS and never execute locally
    (.cursorrules #1). Any implementation must pass `tethricor_runtime.testing` conformance.
    """

    @abstractmethod
    def create_session(
        self,
        profile: str,
        *,
        ttl_seconds: Optional[int] = None,
        repo_url: Optional[str] = None,
        ref: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> dict:
        ...

    @abstractmethod
    def get_session(self, session_id: str) -> dict:
        ...

    @abstractmethod
    def delete_session(self, session_id: str) -> None:
        ...

    @abstractmethod
    def start_exec(
        self,
        session_id: str,
        argv: List[str],
        *,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout_sec: Optional[int] = None,
    ) -> dict:
        ...

    @abstractmethod
    def stream_events(self, session_id: str, exec_id: str) -> Iterator[dict]:
        ...

    @abstractmethod
    def download_artifact(self, session_id: str, name: str) -> bytes:
        ...

    def close(self) -> None:  # optional; default no-op
        return None

    def __enter__(self) -> "SandboxProvider":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


class HarnessAdapter(ABC):
    """Maps a harness onto {gateway, mcp, sandbox}.

    Concrete adapters expose `name`, `default_profile`, and `pre_artifact_argv`, and
    produce the session exec environment (gateway routing + provider-key scrub +
    harness-specific hardening). `entrypoint`/`task_arg` describe how a natural-language
    task is turned into the harness launch command (task intake); override `run_argv`
    for harnesses whose invocation is not a simple `entrypoint [task_arg] <task>`.
    """

    name: str
    default_profile: str
    pre_artifact_argv: Optional[List[str]]
    # Task intake: conventional launch command + how the task string is passed.
    entrypoint: List[str] = []
    task_arg: Optional[str] = None

    @abstractmethod
    def session_env(self, gateway_url: str, mcp_url: str) -> Dict[str, str]:
        ...

    def run_argv(self, task: Optional[str] = None, argv: Optional[List[str]] = None) -> List[str]:
        """Resolve the command to forward to the sandbox.

        Explicit `argv` is forwarded verbatim (advanced/back-compat). Otherwise the
        `task` string is turned into the harness's conventional launch command. The
        conventional command is a sane default; pin it per harness build if it differs.
        """
        if argv:
            return list(argv)
        if not task:
            raise ValueError("run_argv requires either a task string or explicit argv")
        if not self.entrypoint:
            raise ValueError(f"harness {self.name!r} has no task entrypoint; pass explicit argv")
        return list(self.entrypoint) + ([self.task_arg, task] if self.task_arg else [task])


class ModelRouter(ABC):
    """Resolves model routing onto an OpenAI-compatible endpoint (AgentGateway)."""

    @abstractmethod
    def llm_env(self, gateway_url: str) -> Dict[str, str]:
        ...

    def secret_env(self) -> Dict[str, str]:
        """Credentials that must survive the adapter's provider-key scrub.

        Default: none — gateway routing needs no in-session provider key (.cursorrules
        #2). ONLY a local escape-hatch router (e.g. direct Azure OpenAI, used when no
        AgentGateway is available yet) returns a key here. Never use in production.
        """
        return {}
