"""Conformance-gate the microsandbox provider against a fake microsandbox backend.

The fake mirrors the pinned REST surface in `_provider.py`; it executes commands in a
temp workspace via the shared test-double helpers (a stand-in for the real microVM), so
the provider's contract translation is verified end-to-end and hermetically (no real
microsandbox / KVM needed in CI).
"""
from __future__ import annotations

import pathlib
import socket
import sys
import tempfile
import threading
import time
import uuid

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

_ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_ROOT / "shim"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from tethricor_runtime import registry  # noqa: E402
from tethricor_runtime.testing import assert_sandbox_conformance, run_in_workspace, zip_workspace  # noqa: E402

from tethricor_sandbox_microsandbox import MicrosandboxProvider, make_provider  # noqa: E402

_PROFILES = {"python312", "node20", "minimal"}


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _fake_microsandbox() -> FastAPI:
    app = FastAPI()
    boxes: dict[str, str] = {}  # id -> workspace dir

    @app.post("/api/v1/sandboxes", status_code=201)
    async def create(req: Request):
        body = await req.json()
        template = body.get("template")
        if template not in _PROFILES:
            return _err(400, "invalid_profile", f"unknown template {template!r}")
        sid = uuid.uuid4().hex
        boxes[sid] = tempfile.mkdtemp(prefix="msb-")
        return {"id": sid, "status": "running"}

    @app.get("/api/v1/sandboxes/{sid}")
    async def get(sid: str):
        if sid not in boxes:
            return _err(404, "not_found", "no such sandbox")
        return {"id": sid, "status": "running"}

    @app.delete("/api/v1/sandboxes/{sid}", status_code=204)
    async def delete(sid: str):
        boxes.pop(sid, None)
        return Response(status_code=204)

    @app.post("/api/v1/sandboxes/{sid}/exec")
    async def execute(sid: str, req: Request):
        if sid not in boxes:
            return _err(404, "not_found", "no such sandbox")
        body = await req.json()
        result = run_in_workspace(body["command"], boxes[sid])
        return {
            "execId": uuid.uuid4().hex,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exitCode": result.exit_code,
        }

    @app.get("/api/v1/sandboxes/{sid}/fs/archive")
    async def archive(sid: str):
        if sid not in boxes:
            return _err(404, "not_found", "no such sandbox")
        return Response(content=zip_workspace(boxes[sid]), media_type="application/zip")

    return app


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def base_url():
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(_fake_microsandbox(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "fake microsandbox did not start"
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def test_microsandbox_provider_conformance(base_url):
    argv = [sys.executable, "-c", "open('newfile.txt','w').write('generated'); print('task-done')"]
    assert_sandbox_conformance(
        lambda: MicrosandboxProvider(base_url=base_url),
        profile="python312",
        argv=argv,
        expect_stdout="task-done",
        expect_artifact_member="newfile.txt",
        repo_url=None,
    )


def test_factory_registers_in_registry(base_url):
    registry.register_sandbox("microsandbox", make_provider)
    assert "microsandbox" in registry.available_sandboxes()
    provider = registry.get_sandbox_provider("microsandbox", base_url=base_url)
    try:
        assert isinstance(provider, MicrosandboxProvider)
    finally:
        provider.close()
