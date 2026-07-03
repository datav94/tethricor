"""Tests for the local-only direct Azure OpenAI utility.

Verifies the escape-hatch router (a) targets Azure rather than the gateway, (b) carries
the API key through the adapter's provider-key scrub via `secret_env`, and (c) leaves the
default gateway path byte-identical (regression: keys still scrubbed).
"""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "shim"))

from tethricor import direct_azure  # noqa: E402
from tethricor.direct_azure import AzureOpenAIRouter, use_direct_azure_openai  # noqa: E402
from tethricor_runtime.adapters import adapter_for  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_router(monkeypatch):
    # Ensure no leftover selection from another test, and always revert afterwards.
    monkeypatch.delenv("TETHRICOR_MODEL_ROUTER", raising=False)
    monkeypatch.delenv(direct_azure.API_KEY_ENV, raising=False)
    yield
    direct_azure.disable()


def _router() -> AzureOpenAIRouter:
    return AzureOpenAIRouter(
        endpoint="https://res.openai.azure.com/",
        deployment="gpt-4o",
        api_key="secret-key",
        api_version="2024-10-21",
    )


def test_llm_env_targets_azure_not_gateway():
    env = _router().llm_env("http://agentgateway:8080")
    assert env["AZURE_OPENAI_ENDPOINT"] == "https://res.openai.azure.com"
    assert env["AZURE_OPENAI_DEPLOYMENT"] == "gpt-4o"
    assert env["AZURE_OPENAI_API_VERSION"] == "2024-10-21"
    # OpenAI-compatible base URL points at the deployment, never at the gateway.
    assert env["OPENAI_BASE_URL"].startswith(
        "https://res.openai.azure.com/openai/deployments/gpt-4o?api-version="
    )
    assert "agentgateway" not in env["OPENAI_BASE_URL"]
    # The key is never emitted as non-secret routing config.
    assert "AZURE_OPENAI_API_KEY" not in env


def test_secret_env_carries_the_key():
    secret = _router().secret_env()
    assert secret["AZURE_OPENAI_API_KEY"] == "secret-key"
    assert secret["OPENAI_API_KEY"] == "secret-key"


def test_session_env_key_survives_scrub_when_selected(monkeypatch):
    from tethricor_runtime import model

    model.register_router(direct_azure.ROUTER_NAME, _router())
    monkeypatch.setenv("TETHRICOR_MODEL_ROUTER", direct_azure.ROUTER_NAME)

    env = adapter_for("hermes").session_env("http://agentgateway:8080", "http://mcp")
    # Azure routing applied...
    assert env["AZURE_OPENAI_ENDPOINT"] == "https://res.openai.azure.com"
    assert env["OPENAI_BASE_URL"].startswith("https://res.openai.azure.com/")
    # ...and the key survived the provider-key scrub.
    assert env["AZURE_OPENAI_API_KEY"] == "secret-key"
    assert env["OPENAI_API_KEY"] == "secret-key"


def test_default_gateway_path_still_scrubs_keys():
    # With no router selected, the default gateway router routes at the gateway and
    # contributes no secret_env -> provider keys stay blanked (unchanged behavior).
    env = adapter_for("hermes").session_env("http://agentgateway:8080", "http://mcp")
    assert env["OPENAI_BASE_URL"] == "http://agentgateway:8080"
    assert env["AZURE_OPENAI_API_KEY"] == ""
    assert env["OPENAI_API_KEY"] == ""


def test_use_direct_azure_openai_activates_and_disables(monkeypatch):
    import os

    from tethricor_runtime import model

    use_direct_azure_openai(
        endpoint="https://res.openai.azure.com",
        deployment="gpt-4o",
        api_key="k2",
    )
    assert os.environ["TETHRICOR_MODEL_ROUTER"] == direct_azure.ROUTER_NAME
    assert isinstance(model.default_router(), AzureOpenAIRouter)

    direct_azure.disable()
    assert "TETHRICOR_MODEL_ROUTER" not in os.environ
    assert model.default_router() is model.get_router(model.GATEWAY_ROUTER)


def test_build_router_reads_key_from_env(monkeypatch):
    monkeypatch.setenv(direct_azure.API_KEY_ENV, "env-key")
    router = direct_azure.build_router(endpoint="https://r.openai.azure.com", deployment="d")
    assert router.api_key == "env-key"
    assert router.api_version == direct_azure.DEFAULT_API_VERSION


def test_build_router_requires_a_key():
    with pytest.raises(ValueError, match="no Azure OpenAI API key"):
        direct_azure.build_router(endpoint="https://r.openai.azure.com", deployment="d")


def test_build_router_from_config():
    router = direct_azure.build_router_from_config(
        {"endpoint": "https://r.openai.azure.com", "deployment": "d", "api_version": "2025-01-01"},
        api_key="ck",
    )
    assert router.deployment == "d"
    assert router.api_version == "2025-01-01"
    assert router.api_key == "ck"
