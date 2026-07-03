"""Conformance-gate the E2B provider against a fake `E2BSandboxClient` seam.

The fake seam executes commands in a temp workspace via the shared test-double helpers
(a stand-in for an E2B microVM), so the provider's contract translation is verified
hermetically — no E2B account/keys needed. The real SDK binding (`_sdk.py`) is covered
by integration, not this CI run.
"""
from __future__ import annotations

import pathlib
import shutil
import sys
import tempfile
import uuid
from typing import Dict, List, Optional

_ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "shim"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tethricor_runtime.interfaces import RuntimeError_  # noqa: E402
from tethricor_runtime.testing import LocalExec, assert_sandbox_conformance, run_in_workspace, zip_workspace  # noqa: E402

from tethricor_sandbox_e2b import E2BProvider  # noqa: E402

_TEMPLATES = {"python312", "node20", "base"}


class FakeE2BClient:
    """In-memory E2B seam: one temp workspace per sandbox, executed locally (test only)."""

    def __init__(self) -> None:
        self._boxes: Dict[str, str] = {}

    def start(self, template: str, *, timeout_seconds: Optional[int]) -> str:
        if template not in _TEMPLATES:
            raise RuntimeError_("invalid_profile", f"unknown template {template!r}", 400)
        sid = uuid.uuid4().hex
        self._boxes[sid] = tempfile.mkdtemp(prefix="e2b-")
        return sid

    def running(self, sandbox_id: str) -> bool:
        return sandbox_id in self._boxes

    def kill(self, sandbox_id: str) -> None:
        workspace = self._boxes.pop(sandbox_id, None)
        if workspace:
            shutil.rmtree(workspace, ignore_errors=True)

    def run(self, sandbox_id: str, argv: List[str], *, env=None, timeout_sec=None) -> LocalExec:
        if sandbox_id not in self._boxes:
            raise RuntimeError_("not_found", "no such sandbox", 404)
        return run_in_workspace(argv, self._boxes[sandbox_id])

    def download(self, sandbox_id: str) -> bytes:
        if sandbox_id not in self._boxes:
            raise RuntimeError_("not_found", "no such sandbox", 404)
        return zip_workspace(self._boxes[sandbox_id])


def test_e2b_provider_conformance():
    seam = FakeE2BClient()
    argv = [sys.executable, "-c", "open('newfile.txt','w').write('generated'); print('task-done')"]
    assert_sandbox_conformance(
        lambda: E2BProvider(seam),
        profile="python312",
        argv=argv,
        expect_stdout="task-done",
        expect_artifact_member="newfile.txt",
        repo_url=None,
    )
