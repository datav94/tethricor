"""Real E2B binding: implements the `E2BSandboxClient` seam over the `e2b` SDK.

The `e2b` package is an OPTIONAL dependency, imported lazily inside `start()` so the
provider can be constructed (and registered) without it installed. This binding is the
one part that needs a live E2B account/keys, so it is exercised in integration (not the
hermetic CI conformance run, which uses a fake seam). Pin the SDK surface here.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from tethricor_runtime.interfaces import RuntimeError_

from ._provider import ExecOutput


class _Output:
    def __init__(self, stdout: str, stderr: str, exit_code: int) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.exit_code = exit_code


class E2BSdkClient:
    """Wraps `e2b.Sandbox` behind the provider seam."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        self._api_key = api_key
        self._sandboxes: Dict[str, object] = {}

    def start(self, template: str, *, timeout_seconds: Optional[int]) -> str:
        try:
            from e2b import Sandbox  # optional dependency, imported on first use
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise RuntimeError_("dependency_missing", "install the 'sdk' extra: pip install 'tethricor-sandbox-e2b[sdk]'", 500) from exc
        try:
            sbx = Sandbox(template=template, api_key=self._api_key, timeout=timeout_seconds)
        except Exception as exc:  # pragma: no cover - network/credentials
            raise RuntimeError_("invalid_profile", str(exc), 400) from exc
        self._sandboxes[sbx.sandbox_id] = sbx
        return sbx.sandbox_id

    def _sbx(self, sandbox_id: str):
        sbx = self._sandboxes.get(sandbox_id)
        if sbx is None:
            raise RuntimeError_("not_found", "no such sandbox", 404)
        return sbx

    def running(self, sandbox_id: str) -> bool:
        return sandbox_id in self._sandboxes

    def kill(self, sandbox_id: str) -> None:
        sbx = self._sandboxes.pop(sandbox_id, None)
        if sbx is not None:  # pragma: no cover - network
            sbx.kill()

    def run(
        self, sandbox_id: str, argv: List[str], *, env: Optional[Dict[str, str]], timeout_sec: Optional[int]
    ) -> ExecOutput:  # pragma: no cover - network
        sbx = self._sbx(sandbox_id)
        cmd = " ".join(argv)
        res = sbx.commands.run(cmd, envs=env or {}, timeout=timeout_sec)
        return _Output(getattr(res, "stdout", ""), getattr(res, "stderr", ""), int(getattr(res, "exit_code", 0)))

    def download(self, sandbox_id: str) -> bytes:  # pragma: no cover - network
        sbx = self._sbx(sandbox_id)
        # E2B exposes a filesystem API; a real build zips the workspace and returns it.
        data = sbx.files.read("/home/user/changes.zip", format="bytes")
        return bytes(data)
