"""Reusable SandboxProvider conformance kit.

Any `SandboxProvider` (the enterprise runtime, or a third-party package like an E2B or
microsandbox provider) must pass `assert_sandbox_conformance` to be considered
contract-compliant (see FRAMEWORK_EVOLUTION.md §3 gap #7 / §5). It exercises the full
lifecycle over the real provider methods: create -> exec -> SSE -> artifact -> delete,
plus error mapping. Uses plain asserts so it works both under pytest and standalone.
"""
from __future__ import annotations

import io
import pathlib
import subprocess
import zipfile
from dataclasses import dataclass
from typing import Callable, List, Optional

from .interfaces import RuntimeError_, SandboxProvider

ProviderFactory = Callable[[], SandboxProvider]


# --- test-double execution primitives -------------------------------------
# Shared by sandbox-provider test doubles (the in-package fake backends) so the
# execute-in-a-workspace + snapshot-changed-files behavior is defined ONCE, not
# copy-pasted into every provider package (.cursorrules #6). These run subprocesses
# and are for TESTS ONLY — production execution is always forwarded to a real,
# isolated sandbox backend (.cursorrules #1).
@dataclass
class LocalExec:
    stdout: str
    stderr: str
    exit_code: int


def run_in_workspace(argv: List[str], workspace: str, *, timeout: Optional[float] = None) -> LocalExec:
    """Run `argv` inside `workspace` and capture its output (test doubles only)."""
    proc = subprocess.run(
        argv, cwd=workspace, capture_output=True, text=True, timeout=timeout
    )
    return LocalExec(stdout=proc.stdout, stderr=proc.stderr, exit_code=proc.returncode)


def zip_workspace(workspace: str) -> bytes:
    """Zip every file under `workspace` (a stand-in for a changed-files artifact)."""
    root = pathlib.Path(workspace)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(root).as_posix())
    return buf.getvalue()


def assert_sandbox_conformance(
    make_provider: ProviderFactory,
    *,
    profile: str,
    argv: List[str],
    expect_stdout: str,
    artifact_name: str = "changes.zip",
    expect_artifact_member: Optional[str] = None,
    repo_url: Optional[str] = None,
) -> None:
    """Assert a provider satisfies the sandbox execution contract.

    `argv` should create `expect_artifact_member` (if given) and print `expect_stdout`.
    """
    # --- lifecycle + exec + SSE + artifact ---------------------------------
    with make_provider() as provider:
        session = provider.create_session(profile, repo_url=repo_url, ttl_seconds=300)
        assert session.get("id"), "create_session must return an id"
        assert session.get("state") in {"pending", "running"}, "session must start running"
        sid = session["id"]

        rec = provider.start_exec(sid, argv, timeout_sec=60)
        assert rec.get("id"), "start_exec must return an exec id (202)"

        events = list(provider.stream_events(sid, rec["id"]))
        types = [e.get("type") for e in events]
        assert "exit" in types, "event stream must terminate with an exit event"
        exit_ev = next(e for e in events if e.get("type") == "exit")
        assert exit_ev.get("code") == 0, f"task should exit 0, got {exit_ev.get('code')}"
        assert any(
            e.get("type") == "stdout" and e.get("data") == expect_stdout for e in events
        ), f"expected stdout {expect_stdout!r} in stream"

        data = provider.download_artifact(sid, artifact_name)
        assert isinstance(data, (bytes, bytearray)) and data, "artifact must be non-empty bytes"
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            if expect_artifact_member is not None:
                assert expect_artifact_member in names, f"{expect_artifact_member} missing from artifact"

        provider.delete_session(sid)

    # --- post-delete + error mapping --------------------------------------
    with make_provider() as provider:
        try:
            provider.get_session(sid)
            raise AssertionError("get_session on a deleted session must raise")
        except RuntimeError_ as exc:
            assert exc.status == 404, f"deleted session must map to 404, got {exc.status}"

        try:
            provider.create_session("definitely-not-a-real-profile")
            raise AssertionError("unknown profile must be rejected")
        except RuntimeError_ as exc:
            assert exc.status == 400, f"bad profile must map to 400, got {exc.status}"
