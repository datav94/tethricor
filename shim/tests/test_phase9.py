"""Phase 9 shim-side features: adapter task-intake (run_argv) + observability callbacks."""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "shim"))

from tethricor_runtime.adapters import adapter_for  # noqa: E402
from tethricor_runtime.config import Settings  # noqa: E402
from tethricor_runtime.observability import Callbacks  # noqa: E402
from tethricor_runtime.orchestrator import run_task  # noqa: E402


# --- adapter task intake (run_argv) ---------------------------------------
def test_run_argv_builds_task_command_with_flag():
    assert adapter_for("hermes").run_argv(task="do a thing") == ["hermes", "run", "--task", "do a thing"]


def test_run_argv_positional_task():
    assert adapter_for("opencode").run_argv(task="do a thing") == ["opencode", "run", "do a thing"]


def test_run_argv_passthrough_argv_verbatim():
    argv = ["python", "-c", "print(1)"]
    assert adapter_for("hermes").run_argv(argv=argv) == argv


def test_run_argv_requires_task_or_argv():
    with pytest.raises(ValueError):
        adapter_for("hermes").run_argv()


def test_feynman_shares_pi_intake():
    assert adapter_for("feynman").run_argv(task="research x")[:2] == ["pi", "run"]


# --- observability callbacks ----------------------------------------------
class _Recorder(Callbacks):
    def __init__(self):
        self.calls = []

    def on_session_start(self, session):
        self.calls.append(("session_start", session.get("id")))

    def on_exec_start(self, exec_rec, argv):
        self.calls.append(("exec_start", argv[0]))

    def on_event(self, event):
        self.calls.append(("event", event.get("type")))

    def on_artifact(self, path):
        self.calls.append(("artifact", path))

    def on_session_end(self, session_id, *, exit_code):
        self.calls.append(("session_end", exit_code))


def test_callbacks_fire_across_lifecycle(base_url, tmp_path):
    out = tmp_path / "changes.zip"
    settings = Settings(
        harness_type="hermes",
        runtime_url=base_url,
        gateway_url="http://gw:8080",
        mcp_url="http://gw:8080/mcp",
        config={"runtime": {"profile": "python312", "timeout_seconds": 60}},
    )
    rec = _Recorder()
    argv = [sys.executable, "-c", "open('f.txt','w').write('x'); print('hi')"]
    result = run_task(settings, argv, output_path=str(out), callbacks=rec)

    assert result.exit_code == 0
    kinds = [c[0] for c in rec.calls]
    assert kinds[0] == "session_start"
    assert "exec_start" in kinds
    assert ("event", "exit") in rec.calls
    assert ("artifact", str(out)) in rec.calls
    assert rec.calls[-1] == ("session_end", 0)
