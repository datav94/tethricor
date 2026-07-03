"""Shared fixtures for shim tests: a live mock-sandbox server (one per session)."""
from __future__ import annotations

import pathlib
import socket
import threading
import time

import pytest
import uvicorn

_ROOT = pathlib.Path(__file__).resolve().parents[2]
import sys

sys.path.insert(0, str(_ROOT / "shim"))
sys.path.insert(0, str(_ROOT / "local-dev"))

from mock_sandbox import app as mock_app  # noqa: E402


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def base_url():
    """Run the mock-sandbox as a real uvicorn server for the whole test session."""
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(mock_app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "mock-sandbox did not start"
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)
