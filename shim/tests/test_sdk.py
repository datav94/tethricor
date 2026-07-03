"""tethricor SDK facade tests: the plug-and-play `Harness` end-to-end against mock_sandbox."""
from __future__ import annotations

import io
import pathlib
import subprocess
import sys
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "shim"))

from tethricor import Event, Harness, SandboxSession, TaskResult  # noqa: E402


def _make_git_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    repo = tmp_path / "srcrepo"
    repo.mkdir()
    (repo / "README.md").write_text("hello\n")
    import os

    env = {
        **dict(os.environ),
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@e",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@e",
    }
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, env=env)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True, env=env)
    return repo


def test_harness_run_end_to_end(base_url, tmp_path):
    repo = _make_git_repo(tmp_path)
    out = tmp_path / "changes.zip"

    harness = Harness(
        "hermes",
        sandbox="remote-runtime",
        model="gpt-4o-standard",
        source=str(repo),
        runtime_profile="python312",
        timeout_seconds=60,
        runtime_url=base_url,
        gateway_url="http://gw:8080",
        mcp_url="http://gw:8080/mcp",
    )
    assert harness.sandbox == "remote-runtime"

    script = "open('newfile.txt','w').write('generated'); print('task-done')"
    result = harness.run([sys.executable, "-c", script], output_path=str(out))

    assert isinstance(result, TaskResult)
    assert result.ok and result.exit_code == 0
    assert all(isinstance(e, Event) for e in result.events)
    assert any(e.type == "stdout" and e.data == "task-done" for e in result.events)
    assert out.exists()
    with zipfile.ZipFile(io.BytesIO(out.read_bytes())) as zf:
        assert "newfile.txt" in zf.namelist()


def test_harness_from_config_dict(base_url, tmp_path):
    repo = _make_git_repo(tmp_path)
    out = tmp_path / "changes.zip"
    cfg = {
        "harness": {"type": "hermes"},
        "model": {"routing_profile": "gpt-4o-standard"},
        "runtime": {"profile": "python312", "timeout_seconds": 60, "provider": "enterprise-runtime"},
        "source": {"repo_url": str(repo)},
    }
    harness = Harness.from_config(cfg, runtime_url=base_url, gateway_url="http://gw:8080", mcp_url="http://gw:8080/mcp")
    result = harness.run([sys.executable, "-c", "print('ok')"], output_path=str(out))
    assert result.ok


def test_harness_open_session(base_url):
    harness = Harness("hermes", sandbox="remote-runtime", runtime_url=base_url)
    session = harness.open_session()
    assert isinstance(session, SandboxSession)
    assert session.id and session.profile == "python312"
