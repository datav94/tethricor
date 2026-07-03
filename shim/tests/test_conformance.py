"""Framework v0: sandbox registry + SandboxProvider conformance of remote-runtime
(the generic REST/SSE client) and its deprecated enterprise-runtime alias."""
from __future__ import annotations

import pathlib
import sys

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "shim"))

from tethricor_runtime.interfaces import SandboxProvider  # noqa: E402
from tethricor_runtime.registry import (  # noqa: E402
    ENTERPRISE_RUNTIME,
    REMOTE_RUNTIME,
    available_sandboxes,
    get_sandbox_provider,
)
from tethricor_runtime.runtime_client import RuntimeClient  # noqa: E402
from tethricor_runtime.testing import assert_sandbox_conformance  # noqa: E402


def test_registry_has_remote_runtime():
    assert REMOTE_RUNTIME in available_sandboxes()
    provider = get_sandbox_provider(REMOTE_RUNTIME, base_url="http://unused")
    assert isinstance(provider, SandboxProvider)
    assert isinstance(provider, RuntimeClient)
    provider.close()


def test_registry_enterprise_runtime_is_deprecated_alias_for_remote_runtime():
    assert ENTERPRISE_RUNTIME in available_sandboxes()
    alias_provider = get_sandbox_provider(ENTERPRISE_RUNTIME, base_url="http://unused")
    canonical_provider = get_sandbox_provider(REMOTE_RUNTIME, base_url="http://unused")
    assert type(alias_provider) is type(canonical_provider) is RuntimeClient
    alias_provider.close()
    canonical_provider.close()


def test_registry_unknown_provider_raises():
    with pytest.raises(KeyError):
        get_sandbox_provider("no-such-provider")


def test_remote_runtime_passes_conformance(base_url):
    assert_sandbox_conformance(
        lambda: get_sandbox_provider(REMOTE_RUNTIME, base_url=base_url),
        profile="python312",
        argv=[sys.executable, "-c", "open('conf.txt','w').write('x'); print('conf-done')"],
        expect_stdout="conf-done",
        expect_artifact_member="conf.txt",
    )
