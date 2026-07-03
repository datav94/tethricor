"""Integration tests for mock_sandbox against the vendored contract."""
from __future__ import annotations

import io
import json
import pathlib
import sys
import zipfile

from fastapi.testclient import TestClient

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from mock_sandbox import app  # noqa: E402

client = TestClient(app)


def _parse_sse(text: str) -> list[dict]:
    events = []
    for line in text.splitlines():
        if line.startswith("data: "):
            events.append(json.loads(line[len("data: "):]))
    return events


def test_healthz_and_profiles():
    assert client.get("/healthz").json() == {"status": "ok"}
    profiles = client.get("/v1/profiles").json()["profiles"]
    assert "python312" in profiles and "node20" in profiles


def test_create_rejects_unknown_profile():
    r = client.post("/v1/sessions", json={"profile": "nope"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid_input"


def test_exec_stream_and_artifact_roundtrip():
    # create
    r = client.post("/v1/sessions", json={"profile": "python312"})
    assert r.status_code == 201
    sid = r.json()["id"]
    assert r.json()["state"] == "running"

    # exec: write a file into the workspace and print a line
    script = "open('newfile.txt','w').write('hello'); print('done')"
    r = client.post(f"/v1/sessions/{sid}/exec", json={"argv": [sys.executable, "-c", script]})
    assert r.status_code == 202
    exec_id = r.json()["id"]

    # stream events (blocks until exit)
    r = client.get(f"/v1/sessions/{sid}/exec/{exec_id}/events")
    assert r.status_code == 200
    events = _parse_sse(r.text)
    types = [e["type"] for e in events]
    assert "exit" in types
    exit_ev = next(e for e in events if e["type"] == "exit")
    assert exit_ev["code"] == 0
    assert any(e["type"] == "stdout" and e["data"] == "done" for e in events)

    # artifact: zip should contain the created file
    r = client.get(f"/v1/sessions/{sid}/artifacts/changes.zip")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = zf.namelist()
        assert "newfile.txt" in names
        assert zf.read("newfile.txt") == b"hello"

    # delete + confirm gone
    assert client.delete(f"/v1/sessions/{sid}").status_code == 204
    assert client.get(f"/v1/sessions/{sid}").status_code == 404


def test_exec_on_missing_session_404():
    r = client.post("/v1/sessions/does-not-exist/exec", json={"argv": ["true"]})
    assert r.status_code == 404
