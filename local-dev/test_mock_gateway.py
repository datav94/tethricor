"""Tests for the mock-gateway (AgentGateway double)."""
from __future__ import annotations

import pathlib
import sys

from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from mock_gateway import app  # noqa: E402

client = TestClient(app)


def test_healthz_and_models():
    assert client.get("/healthz").json() == {"status": "ok"}
    ids = {m["id"] for m in client.get("/v1/models").json()["data"]}
    assert "gpt-4o-standard" in ids


def test_chat_completion_echoes_last_user_message():
    body = {
        "model": "gpt-4o-standard",
        "messages": [
            {"role": "system", "content": "be nice"},
            {"role": "user", "content": "hello there"},
        ],
    }
    resp = client.post("/v1/chat/completions", json=body).json()
    assert resp["object"] == "chat.completion"
    content = resp["choices"][0]["message"]["content"]
    assert "hello there" in content


def test_chat_completion_handles_content_parts():
    body = {
        "model": "gpt-4o-standard",
        "messages": [{"role": "user", "content": [{"type": "text", "text": "parts-form"}]}],
    }
    content = client.post("/v1/chat/completions", json=body).json()["choices"][0]["message"]["content"]
    assert "parts-form" in content
