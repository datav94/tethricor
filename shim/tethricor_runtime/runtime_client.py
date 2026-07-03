"""Generic REST/SSE client for any service implementing the sandbox execution contract.

Implements exactly the contract in api-spec/sandbox-execution-contract.yaml:
sessions -> async exec (202) -> SSE events (stdout|stderr|exit|error) -> artifact
download -> delete. Point it (via TETHRICOR_RUNTIME_URL / base_url) at whatever
implements that contract: something you self-host, a vendor's service, or the bundled
`local-dev/mock_sandbox.py` test double for local dev. Registered as the `remote-runtime`
sandbox provider (`enterprise-runtime` is a deprecated alias for the same class). This is
the ONLY way the shim runs code; there is no local execution path (.cursorrules #1).
"""
from __future__ import annotations

import json
from typing import Dict, Iterator, List, Optional

import httpx

# Exceptions are defined with the SandboxProvider contract; re-exported here so existing
# imports (`from tethricor_runtime.runtime_client import RuntimeError_, SessionExpired`) keep working.
from .interfaces import RuntimeError_, SandboxProvider, SessionExpired

__all__ = ["RuntimeClient", "RuntimeError_", "SessionExpired"]


class RuntimeClient(SandboxProvider):
    """Reference `SandboxProvider`: the enterprise agent-runtime over REST/SSE."""

    def __init__(
        self,
        base_url: str = "",
        *,
        client: Optional[httpx.Client] = None,
        timeout: float = 30.0,
    ) -> None:
        # An injected client (e.g. ASGITransport for tests) already carries base_url.
        self._owns_client = client is None
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout)

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "RuntimeClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- helpers -----------------------------------------------------------
    @staticmethod
    def _raise(resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        code, message = "internal", resp.text
        try:
            err = resp.json().get("error", {})
            code = err.get("code", code)
            message = err.get("message", message)
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
        body: Dict[str, object] = {"profile": profile}
        if ttl_seconds is not None:
            body["ttlSeconds"] = ttl_seconds
        if repo_url:
            body["repoUrl"] = repo_url
        if ref:
            body["ref"] = ref
        if metadata:
            body["metadata"] = metadata
        resp = self._client.post("/v1/sessions", json=body)
        self._raise(resp)
        return resp.json()

    def get_session(self, session_id: str) -> dict:
        resp = self._client.get(f"/v1/sessions/{session_id}")
        self._raise(resp)
        return resp.json()

    def delete_session(self, session_id: str) -> None:
        resp = self._client.delete(f"/v1/sessions/{session_id}")
        # 404 on delete is benign (already gone); anything else surfaces.
        if resp.status_code not in (204, 404):
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
        body: Dict[str, object] = {"argv": argv}
        if cwd:
            body["cwd"] = cwd
        if env:
            body["env"] = env
        if timeout_sec is not None:
            body["timeoutSec"] = timeout_sec
        resp = self._client.post(f"/v1/sessions/{session_id}/exec", json=body)
        self._raise(resp)
        return resp.json()

    def stream_events(self, session_id: str, exec_id: str) -> Iterator[dict]:
        """Yield decoded SSE frames until (and including) the terminating `exit`."""
        url = f"/v1/sessions/{session_id}/exec/{exec_id}/events"
        with self._client.stream("GET", url, timeout=None) as resp:
            self._raise(resp)
            for line in resp.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                try:
                    event = json.loads(line[len("data: "):])
                except json.JSONDecodeError:
                    continue
                yield event
                if event.get("type") == "exit":
                    return

    # -- artifacts (code OUT) ---------------------------------------------
    def download_artifact(self, session_id: str, name: str) -> bytes:
        resp = self._client.get(f"/v1/sessions/{session_id}/artifacts/{name}")
        self._raise(resp)
        return resp.content
