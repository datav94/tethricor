"""`e2b` SandboxProvider — adopt, don't build (FRAMEWORK_EVOLUTION §5.2).

E2B is SDK-driven (not a self-host REST we operate), so the contract is translated onto
a small **client seam** (`E2BSandboxClient`). The real binding wraps the `e2b` SDK
(`_sdk.py`); tests inject a fake seam, so the SandboxProvider contract translation is
verified hermetically without E2B API keys. Task code runs in an E2B Firecracker microVM
reached over the SDK/REST — never in the harness container (`.cursorrules` #1).

E2B's self-host infra does not officially target Azure — use it for developer laptops /
non-Azure CI (managed or GCP/AWS self-host), not on-prem Azure prod.
"""
from __future__ import annotations

from typing import Dict, Iterator, List, Optional, Protocol

from tethricor_runtime.interfaces import RuntimeError_, SandboxProvider


class ExecOutput(Protocol):
    stdout: str
    stderr: str
    exit_code: int


class E2BSandboxClient(Protocol):
    """The e2b-specific operations the provider needs.

    Implementations MUST raise `tethricor_runtime.interfaces.RuntimeError_` (status 400 for an
    unknown template, 404 for an unknown/killed sandbox) so error mapping is uniform.
    """

    def start(self, template: str, *, timeout_seconds: Optional[int]) -> str: ...

    def running(self, sandbox_id: str) -> bool: ...

    def kill(self, sandbox_id: str) -> None: ...

    def run(
        self, sandbox_id: str, argv: List[str], *, env: Optional[Dict[str, str]], timeout_sec: Optional[int]
    ) -> ExecOutput: ...

    def download(self, sandbox_id: str) -> bytes: ...


class E2BProvider(SandboxProvider):
    """SandboxProvider contract shell over an `E2BSandboxClient` seam."""

    def __init__(self, client: E2BSandboxClient) -> None:
        self._client = client
        self._execs: Dict[str, ExecOutput] = {}

    def close(self) -> None:  # the seam owns any transport
        return None

    # -- sessions ----------------------------------------------------------
    def create_session(
        self,
        profile: str,
        *,
        ttl_seconds: Optional[int] = None,
        repo_url: Optional[str] = None,
        ref: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> dict:
        sid = self._client.start(profile, timeout_seconds=ttl_seconds)
        if repo_url:
            argv = ["git", "clone", "--depth", "1"]
            if ref:
                argv += ["--branch", ref]
            argv += [repo_url, "."]
            self.start_exec(sid, argv)
        return {"id": sid, "state": "running", "profile": profile}

    def get_session(self, session_id: str) -> dict:
        if not self._client.running(session_id):
            raise RuntimeError_("not_found", "no such sandbox", 404)
        return {"id": session_id, "state": "running"}

    def delete_session(self, session_id: str) -> None:
        self._client.kill(session_id)

    # -- exec --------------------------------------------------------------
    def start_exec(
        self,
        session_id: str,
        argv: List[str],
        *,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        timeout_sec: Optional[int] = None,
    ) -> dict:
        result = self._client.run(session_id, argv, env=env, timeout_sec=timeout_sec)
        exec_id = f"{session_id}:{len(self._execs)}"
        self._execs[exec_id] = result
        return {"id": exec_id}

    def stream_events(self, session_id: str, exec_id: str) -> Iterator[dict]:
        result = self._execs.get(exec_id)
        if result is None:
            yield {"type": "exit", "code": 0}
            return
        for line in (result.stdout or "").splitlines():
            yield {"type": "stdout", "data": line}
        for line in (result.stderr or "").splitlines():
            yield {"type": "stderr", "data": line}
        yield {"type": "exit", "code": int(result.exit_code)}

    # -- artifacts (code OUT) ---------------------------------------------
    def download_artifact(self, session_id: str, name: str) -> bytes:
        return self._client.download(session_id)
