"""`microsandbox` SandboxProvider — adopt, don't build (FRAMEWORK_EVOLUTION §5.2).

Translates the Tethricor SandboxProvider contract (create -> exec -> stream -> artifact ->
delete) onto the microsandbox server's REST API. microsandbox gives real libkrun/KVM
microVM isolation, rootless and local-first, so `.cursorrules` #1 holds: task code runs
in an isolated microVM reached over REST, never in the harness container.

microsandbox is pre-1.0 (beta): the endpoint shapes below are pinned here so a version
bump is a one-file change. Verify against your microsandbox server version.
"""
from __future__ import annotations

import json
from typing import Dict, Iterator, List, Optional

import httpx

from tethricor_runtime.interfaces import RuntimeError_, SandboxProvider, SessionExpired

# --- pinned microsandbox REST surface (beta) ------------------------------
_SANDBOXES = "/api/v1/sandboxes"


def _status_to_state(status: Optional[str]) -> str:
    return {"running": "running", "starting": "pending", "pending": "pending"}.get(
        (status or "").lower(), "running"
    )


class MicrosandboxProvider(SandboxProvider):
    """SandboxProvider backed by a microsandbox server."""

    def __init__(
        self,
        base_url: str = "",
        *,
        api_key: Optional[str] = None,
        client: Optional[httpx.Client] = None,
        timeout: float = 60.0,
    ) -> None:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout, headers=headers)
        # microsandbox exec is request/response; cache results to replay as a stream.
        self._execs: Dict[str, dict] = {}

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    @staticmethod
    def _raise(resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        code, message = "internal", resp.text
        try:
            err = resp.json().get("error", {})
            code, message = err.get("code", code), err.get("message", message)
        except (json.JSONDecodeError, ValueError):
            pass
        if resp.status_code == 410:
            raise SessionExpired(code, message, resp.status_code)
        raise RuntimeError_(code, message, resp.status_code)

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
        body: Dict[str, object] = {"template": profile}
        if ttl_seconds is not None:
            body["ttlSeconds"] = ttl_seconds
        if metadata:
            body["metadata"] = metadata
        resp = self._client.post(_SANDBOXES, json=body)
        self._raise(resp)
        data = resp.json()
        sid = data["id"]
        # Code IN: microsandbox has no clone-on-create, so clone via an init exec.
        if repo_url:
            argv = ["git", "clone", "--depth", "1"]
            if ref:
                argv += ["--branch", ref]
            argv += [repo_url, "."]
            self.start_exec(sid, argv)
        return {"id": sid, "state": _status_to_state(data.get("status")), "profile": profile}

    def get_session(self, session_id: str) -> dict:
        resp = self._client.get(f"{_SANDBOXES}/{session_id}")
        self._raise(resp)
        data = resp.json()
        return {"id": data["id"], "state": _status_to_state(data.get("status"))}

    def delete_session(self, session_id: str) -> None:
        resp = self._client.delete(f"{_SANDBOXES}/{session_id}")
        if resp.status_code not in (200, 202, 204, 404):
            self._raise(resp)

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
        body: Dict[str, object] = {"command": argv}
        if cwd:
            body["cwd"] = cwd
        if env:
            body["env"] = env
        if timeout_sec is not None:
            body["timeoutSec"] = timeout_sec
        resp = self._client.post(f"{_SANDBOXES}/{session_id}/exec", json=body)
        self._raise(resp)
        rec = resp.json()
        exec_id = rec.get("execId") or rec.get("id")
        self._execs[exec_id] = rec
        return {"id": exec_id}

    def stream_events(self, session_id: str, exec_id: str) -> Iterator[dict]:
        """Replay the cached synchronous exec result as our SSE-style event frames."""
        rec = self._execs.get(exec_id, {})
        for line in (rec.get("stdout") or "").splitlines():
            yield {"type": "stdout", "data": line}
        for line in (rec.get("stderr") or "").splitlines():
            yield {"type": "stderr", "data": line}
        yield {"type": "exit", "code": int(rec.get("exitCode", 0))}

    # -- artifacts (code OUT) ---------------------------------------------
    def download_artifact(self, session_id: str, name: str) -> bytes:
        resp = self._client.get(f"{_SANDBOXES}/{session_id}/fs/archive")
        self._raise(resp)
        return resp.content
