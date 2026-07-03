"""Shim tests: adapter hardening, runtime-client error mapping, and a full E2E
against the local mock_sandbox (clone -> exec -> SSE -> artifact -> delete)."""
from __future__ import annotations

import io
import pathlib
import subprocess
import sys
import zipfile

import httpx
import pytest

# Make the shim package and the local-dev mock importable (base_url fixture in conftest).
_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "shim"))
sys.path.insert(0, str(_ROOT / "local-dev"))

from tethricor_runtime.adapters import PROVIDER_KEY_VARS, adapter_for  # noqa: E402
from tethricor_runtime.config import Settings  # noqa: E402
from tethricor_runtime.orchestrator import run_task  # noqa: E402
from tethricor_runtime.runtime_client import RuntimeClient, RuntimeError_, SessionExpired  # noqa: E402


# --- adapters --------------------------------------------------------------
def test_feynman_uses_pi_adapter():
    assert adapter_for("feynman").name == "pi"
    assert adapter_for("pi").name == "pi"


def test_session_env_routes_gateway_and_scrubs_keys():
    env = adapter_for("hermes").session_env("http://gw:8080", "http://gw:8080/mcp")
    assert env["OPENAI_BASE_URL"] == "http://gw:8080"
    assert env["ANTHROPIC_BASE_URL"] == "http://gw:8080"
    for var in PROVIDER_KEY_VARS:
        assert env[var] == ""  # scrubbed
    # Hermes-specific hardening
    assert env["HERMES_DISABLE_MESSAGING"] == "1"
    assert env["HERMES_SANDBOX_BACKEND"] == "agent-runtime"


# --- runtime client error mapping -----------------------------------------
def test_error_mapping_404(base_url):
    with RuntimeClient(base_url) as rc:
        with pytest.raises(RuntimeError_) as exc:
            rc.get_session("nope")
    assert exc.value.status == 404
    assert exc.value.code == "not_found"


def test_error_mapping_410_is_session_expired():
    resp = httpx.Response(410, json={"error": {"code": "session_expired", "message": "gone"}})
    with pytest.raises(SessionExpired):
        RuntimeClient._raise(resp)


def test_bad_profile_rejected(base_url):
    with RuntimeClient(base_url) as rc:
        with pytest.raises(RuntimeError_) as exc:
            rc.create_session("does-not-exist")
    assert exc.value.status == 400


# --- full E2E --------------------------------------------------------------
def _make_git_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    repo = tmp_path / "srcrepo"
    repo.mkdir()
    (repo / "README.md").write_text("hello\n")
    env = {
        **{k: v for k, v in __import__("os").environ.items()},
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@e",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@e",
    }
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True, env=env)
    return repo


def test_run_task_end_to_end(base_url, tmp_path):
    repo = _make_git_repo(tmp_path)
    out = tmp_path / "changes.zip"

    settings = Settings(
        harness_type="hermes",
        runtime_url=base_url,
        gateway_url="http://gw:8080",
        mcp_url="http://gw:8080/mcp",
        config={
            "runtime": {"profile": "python312", "timeout_seconds": 60},
            "source": {"repo_url": str(repo)},
        },
    )

    script = "open('newfile.txt','w').write('generated'); print('task-done')"
    result = run_task(
        settings,
        [sys.executable, "-c", script],
        output_path=str(out),
    )

    assert result.exit_code == 0
    assert any(e["type"] == "stdout" and e["data"] == "task-done" for e in result.events)
    assert out.exists()
    with zipfile.ZipFile(io.BytesIO(out.read_bytes())) as zf:
        assert "newfile.txt" in zf.namelist()

    # session must have been deleted (code OUT complete, no leak)
    with RuntimeClient(base_url) as rc:
        with pytest.raises(RuntimeError_) as exc:
            rc.get_session(result.session_id)
    assert exc.value.status == 404
