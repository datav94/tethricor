"""Plugin discovery + model-router selection tests.

Verifies entry-point discovery registers providers on all three axes and that the model
router is selectable via TETHRICOR_MODEL_ROUTER, without needing an actually-installed plugin.
"""
from __future__ import annotations

import pathlib
import sys
from typing import Dict, List

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "shim"))

from tethricor import discovery  # noqa: E402
from tethricor_runtime import adapters, model, registry  # noqa: E402
from tethricor_runtime.interfaces import HarnessAdapter, ModelRouter, SandboxProvider  # noqa: E402


class _FakeEP:
    def __init__(self, name, obj):
        self.name = name
        self._obj = obj

    def load(self):
        return self._obj


class _FakeSandbox(SandboxProvider):
    def create_session(self, profile, *, ttl_seconds=3600, repo_url=None, ref=None, metadata=None):
        return {"id": "x", "profile": profile, "state": "ready"}

    def get_session(self, session_id):
        return {"id": session_id}

    def delete_session(self, session_id):
        return None

    def start_exec(self, session_id, argv, *, env=None, timeout_sec=600):
        return {"id": "e"}

    def stream_events(self, session_id, exec_id):
        return iter(())

    def download_artifact(self, session_id, name):
        return b""

    def close(self):
        return None


def _fake_sandbox_factory(*, base_url="", client=None, **_):
    return _FakeSandbox()


class _FakeAdapter(HarnessAdapter):
    name = "customharness"
    default_profile = "python312"
    pre_artifact_argv = None

    def session_env(self, gateway_url: str, mcp_url: str) -> Dict[str, str]:
        return {"CUSTOM": "1"}


class _EchoRouter(ModelRouter):
    def llm_env(self, gateway_url: str) -> Dict[str, str]:
        return {"ECHO_BASE_URL": gateway_url}


def test_load_plugins_registers_all_three_axes(monkeypatch):
    groups: Dict[str, List[_FakeEP]] = {
        discovery.GROUP_SANDBOXES: [_FakeEP("fakesandbox", _fake_sandbox_factory)],
        discovery.GROUP_HARNESSES: [_FakeEP("customharness", _FakeAdapter())],
        discovery.GROUP_MODELS: [_FakeEP("echo", _EchoRouter())],
    }
    monkeypatch.setattr(discovery, "_entry_points", lambda group: groups.get(group, []))

    discovery.load_plugins()

    assert "fakesandbox" in registry.available_sandboxes()
    assert isinstance(registry.get_sandbox_provider("fakesandbox"), _FakeSandbox)
    assert adapters.adapter_for("customharness").name == "customharness"
    assert isinstance(model.get_router("echo"), _EchoRouter)


def test_model_router_selectable_via_env(monkeypatch):
    model.register_router("echo2", _EchoRouter())
    monkeypatch.setenv("TETHRICOR_MODEL_ROUTER", "echo2")
    assert isinstance(model.default_router(), _EchoRouter)
    monkeypatch.delenv("TETHRICOR_MODEL_ROUTER", raising=False)
    assert model.default_router() is model.get_router(model.GATEWAY_ROUTER)


def test_unknown_router_raises():
    import pytest

    with pytest.raises(KeyError):
        model.get_router("does-not-exist")
