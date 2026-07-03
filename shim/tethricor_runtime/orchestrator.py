"""Task orchestration: one runtime session per task.

Flow (DESIGN_NOTES §7, Phase 5): create session (clone `source.repo_url`) -> forward
the task as an async `exec` -> stream SSE events -> download the changed-files zip via
the artifact endpoint (code OUT) -> delete the session. TTL is sized from the config
timeout; `410 session_expired` is surfaced cleanly.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

import httpx

from .adapters import adapter_for
from .config import Settings
from .interfaces import SessionExpired
from .observability import Callbacks, _EventOnly
from .registry import get_sandbox_provider

# Extra head-room over the task timeout so the session outlives the exec.
_TTL_MARGIN_SECONDS = 300


@dataclass
class TaskResult:
    session_id: str
    exit_code: Optional[int]
    artifact_path: Optional[str]
    events: List[dict] = field(default_factory=list)


def run_task(
    settings: Settings,
    argv: List[str],
    *,
    output_path: str = "changes.zip",
    artifact_name: str = "changes.zip",
    client: Optional[httpx.Client] = None,
    on_event: Optional[Callable[[dict], None]] = None,
    callbacks: Optional[Callbacks] = None,
) -> TaskResult:
    adapter = adapter_for(settings.harness_type)
    profile = settings.profile or adapter.default_profile
    timeout = settings.timeout_seconds
    # `on_event` is retained as sugar over the richer Callbacks surface (single path).
    cb = callbacks or (_EventOnly(on_event) if on_event else Callbacks())

    rc = get_sandbox_provider(settings.provider, base_url=settings.runtime_url, client=client)
    session = rc.create_session(
        profile,
        ttl_seconds=timeout + _TTL_MARGIN_SECONDS,
        repo_url=settings.repo_url or None,
        ref=settings.ref or None,
        metadata={"harnessType": settings.harness_type},
    )
    session_id = session["id"]
    cb.on_session_start(session)
    events: List[dict] = []
    exit_code: Optional[int] = None
    artifact_written: Optional[str] = None

    try:
        env = adapter.session_env(settings.gateway_url, settings.mcp_url)
        exec_rec = rc.start_exec(session_id, argv, env=env, timeout_sec=timeout)
        cb.on_exec_start(exec_rec, argv)
        for event in rc.stream_events(session_id, exec_rec["id"]):
            events.append(event)
            cb.on_event(event)
            if event.get("type") == "exit":
                exit_code = event.get("code")

        # Optional adapter hook before harvesting the artifact.
        if adapter.pre_artifact_argv:
            pre = rc.start_exec(session_id, adapter.pre_artifact_argv, timeout_sec=timeout)
            for _ in rc.stream_events(session_id, pre["id"]):
                pass

        # Code OUT: pull the changed-files zip.
        data = rc.download_artifact(session_id, artifact_name)
        Path(output_path).write_bytes(data)
        artifact_written = output_path
        cb.on_artifact(artifact_written)
    except SessionExpired:
        # Session died mid-task; nothing to harvest. Surface as a failed result.
        exit_code = exit_code if exit_code is not None else -1
        raise
    finally:
        try:
            rc.delete_session(session_id)
        finally:
            rc.close()
            cb.on_session_end(session_id, exit_code=exit_code)

    return TaskResult(
        session_id=session_id,
        exit_code=exit_code,
        artifact_path=artifact_written,
        events=events,
    )


def print_event(event: dict) -> None:
    typ = event.get("type")
    if typ == "stdout":
        print(event.get("data", ""))
    elif typ == "stderr":
        print(event.get("data", ""), file=sys.stderr)
    elif typ == "error":
        print(f"[runtime-error] {event.get('data', '')}", file=sys.stderr)
    elif typ == "exit":
        print(f"[exit] code={event.get('code')}", file=sys.stderr)
