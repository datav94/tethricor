"""mock-sandbox — a local double for a remote sandbox execution service.

Mirrors the sandbox execution contract in api-spec/sandbox-execution-contract.yaml. It
implements memory-style execution (commands run in the mock's own process space, in a
per-session temp workspace) plus the two Tethricor-relevant behaviors a real backend
needs to provide:

  - `repoUrl` git-clone at session create (code IN)
  - artifact download of a zip of changed files (code OUT)

This is a TEST DOUBLE for local parity only. It is deliberately not isolated and must
never be used as a real sandbox provider (see .cursorrules #1 / DESIGN_NOTES §7).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import uuid
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

PROFILES = [
    "minimal",
    "skills-minimal",
    "git",
    "node20",
    "skill-security-runner",
    "python312",
    "rust",
    "go",
    "polyglot-dev",
]

DEFAULT_TTL_SECONDS = 1800

app = FastAPI(title="mock-sandbox (agent-runtime double)")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(ts: dt.datetime) -> str:
    return ts.isoformat()


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


class Exec:
    """Tracks a single command execution and its streamed events."""

    def __init__(self, exec_id: str, session_id: str) -> None:
        self.id = exec_id
        self.session_id = session_id
        self.created_at = _now()
        self.events: List[dict] = []
        self.done = False
        self.exit_code: Optional[int] = None
        self._lock = threading.Lock()

    def append(self, event: dict) -> None:
        with self._lock:
            self.events.append(event)

    def snapshot(self, start: int) -> tuple[List[dict], bool]:
        with self._lock:
            return self.events[start:], self.done


class Session:
    def __init__(self, profile: str, ttl_seconds: int, metadata: Optional[dict]) -> None:
        self.id = str(uuid.uuid4())
        self.profile = profile
        self.state = "running"
        self.created_at = _now()
        self.expires_at = self.created_at + dt.timedelta(seconds=ttl_seconds)
        self.metadata = metadata or {}
        self.workdir = Path(tempfile.mkdtemp(prefix=f"tethricor-sess-{self.id[:8]}-"))
        self.repo_dir: Optional[Path] = None
        self.execs: Dict[str, Exec] = {}

    @property
    def expired(self) -> bool:
        return _now() > self.expires_at

    def as_json(self) -> dict:
        return {
            "id": self.id,
            "profile": self.profile,
            "state": self.state,
            "createdAt": _iso(self.created_at),
            "expiresAt": _iso(self.expires_at),
            "metadata": self.metadata,
        }

    def cleanup(self) -> None:
        shutil.rmtree(self.workdir, ignore_errors=True)


SESSIONS: Dict[str, Session] = {}


def _clone_repo(session: Session, repo_url: str, ref: str) -> None:
    """Best-effort shallow clone into the session workspace (code IN)."""
    target = session.workdir / "repo"
    cmd = ["git", "clone", "--depth", "1"]
    if ref:
        cmd += ["--branch", ref]
    cmd += [repo_url, str(target)]
    try:
        subprocess.run(cmd, capture_output=True, timeout=120, check=True)
        session.repo_dir = target
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
        # Mock stays usable even if clone fails (e.g. offline); record the reason.
        session.metadata["cloneError"] = str(exc)


def _pump(stream, typ: str, ex: Exec) -> None:
    for raw in iter(stream.readline, b""):
        line = raw.decode("utf-8", "replace").rstrip("\r\n")
        if line.strip() == "":
            continue
        ex.append({"type": typ, "data": line})
    stream.close()


def _run_exec(session: Session, ex: Exec, argv: List[str], cwd: Optional[str], env: Optional[dict], timeout: int) -> None:
    workdir = session.repo_dir or session.workdir
    if cwd:
        workdir = (Path(workdir) / cwd).resolve()
    run_env = dict(os.environ)
    if env:
        run_env.update(env)
    try:
        proc = subprocess.Popen(
            argv,
            cwd=str(workdir),
            env=run_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        ex.append({"type": "error", "data": str(exc)})
        ex.append({"type": "exit", "code": -1})
        ex.exit_code = -1
        ex.done = True
        return

    t_out = threading.Thread(target=_pump, args=(proc.stdout, "stdout", ex), daemon=True)
    t_err = threading.Thread(target=_pump, args=(proc.stderr, "stderr", ex), daemon=True)
    t_out.start()
    t_err.start()

    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        ex.append({"type": "error", "data": f"timeout after {timeout}s"})
        code = -1
    t_out.join(timeout=5)
    t_err.join(timeout=5)
    ex.append({"type": "exit", "code": code})
    ex.exit_code = code
    ex.done = True


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/v1/profiles")
def list_profiles():
    return {"profiles": PROFILES}


@app.post("/v1/sessions")
async def create_session(request: Request):
    body = await request.json()
    profile = body.get("profile")
    if not profile:
        return _err(400, "invalid_input", "profile is required")
    if profile not in PROFILES:
        return _err(400, "invalid_input", f"unknown profile {profile!r}")
    ttl = int(body.get("ttlSeconds") or DEFAULT_TTL_SECONDS)
    session = Session(profile, ttl, body.get("metadata"))
    SESSIONS[session.id] = session

    repo_url = body.get("repoUrl")
    if repo_url:
        _clone_repo(session, repo_url, body.get("ref", ""))

    return JSONResponse(status_code=201, content=session.as_json())


@app.get("/v1/sessions/{session_id}")
def get_session(session_id: str):
    session = SESSIONS.get(session_id)
    if not session:
        return _err(404, "not_found", "session not found")
    if session.expired:
        return _err(410, "session_expired", "session expired")
    return session.as_json()


@app.delete("/v1/sessions/{session_id}")
def delete_session(session_id: str):
    session = SESSIONS.pop(session_id, None)
    if not session:
        return _err(404, "not_found", "session not found")
    session.cleanup()
    return Response(status_code=204)


@app.post("/v1/sessions/{session_id}/exec")
async def start_exec(session_id: str, request: Request):
    session = SESSIONS.get(session_id)
    if not session:
        return _err(404, "not_found", "session not found")
    if session.expired:
        return _err(410, "session_expired", "session expired")
    body = await request.json()
    argv = body.get("argv")
    if not argv:
        return _err(400, "invalid_input", "argv is required")

    ex = Exec(str(uuid.uuid4()), session_id)
    session.execs[ex.id] = ex
    timeout = int(body.get("timeoutSec") or 120)
    threading.Thread(
        target=_run_exec,
        args=(session, ex, argv, body.get("cwd"), body.get("env"), timeout),
        daemon=True,
    ).start()
    return JSONResponse(
        status_code=202,
        content={
            "id": ex.id,
            "sessionId": session_id,
            "createdAt": _iso(ex.created_at),
            "exitCode": None,
        },
    )


@app.get("/v1/sessions/{session_id}/exec/{exec_id}/events")
async def stream_exec(session_id: str, exec_id: str):
    session = SESSIONS.get(session_id)
    if not session:
        return _err(404, "not_found", "session not found")
    ex = session.execs.get(exec_id)
    if not ex:
        return _err(404, "not_found", "exec not found")

    async def event_stream():
        index = 0
        while True:
            new_events, done = ex.snapshot(index)
            for event in new_events:
                yield f"data: {json.dumps(event)}\n\n"
                index += 1
                if event.get("type") == "exit":
                    return
            if done and not new_events:
                return
            await asyncio.sleep(0.05)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _changed_files(session: Session) -> List[Path]:
    """Files to include in the output zip (code OUT)."""
    if session.repo_dir and (session.repo_dir / ".git").exists():
        names: set[str] = set()
        for args in (
            ["git", "-C", str(session.repo_dir), "diff", "--name-only", "HEAD"],
            ["git", "-C", str(session.repo_dir), "ls-files", "--others", "--exclude-standard"],
        ):
            try:
                out = subprocess.run(args, capture_output=True, timeout=30, check=True)
                names.update(line for line in out.stdout.decode().splitlines() if line.strip())
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
                pass
        return [session.repo_dir / n for n in sorted(names) if (session.repo_dir / n).is_file()]
    # No git repo: return everything in the workspace.
    return [p for p in session.workdir.rglob("*") if p.is_file()]


@app.get("/v1/sessions/{session_id}/artifacts/{name}")
def download_artifact(session_id: str, name: str):
    session = SESSIONS.get(session_id)
    if not session:
        return _err(404, "not_found", "session not found")
    if session.expired:
        return _err(410, "session_expired", "session expired")

    base = session.repo_dir or session.workdir
    files = _changed_files(session)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            try:
                arcname = path.relative_to(base)
            except ValueError:
                arcname = path.name
            zf.write(path, arcname.as_posix() if hasattr(arcname, "as_posix") else str(arcname))
    buf.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="{name}"'}
    return StreamingResponse(buf, media_type="application/zip", headers=headers)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
