"""Per-harness adapters.

Each adapter maps a harness onto the three enterprise services (AgentGateway, MCP,
agent-runtime) and expresses the platform-locked hardening the shim applies to the
session exec environment:

  - route all LLM/MCP traffic through AgentGateway (.cursorrules #2)
  - scrub direct provider credentials so the harness cannot bypass the gateway
  - override the harness's native execution/sandbox backend so code runs in the
    agent-runtime, never in the harness container (.cursorrules #1)

`pi` and `feynman` share the Pi adapter (Feynman = Pi + research profile).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .interfaces import HarnessAdapter
from .model import default_router

# Direct-provider credential env names that must NEVER be passed into a session
# (all traffic goes through AgentGateway instead).
PROVIDER_KEY_VARS: List[str] = [
    "OPENAI_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "MISTRAL_API_KEY",
    "GROQ_API_KEY",
]


@dataclass(frozen=True)
class Adapter(HarnessAdapter):
    name: str
    default_profile: str
    # Extra env forced into the session exec for this harness (hardening + overrides).
    extra_env: Dict[str, str] = field(default_factory=dict)
    # Optional command run inside the session before the artifact is downloaded
    # (usually unnecessary: the runtime builds the changed-files zip on demand).
    pre_artifact_argv: Optional[List[str]] = None
    # Task intake (see HarnessAdapter.run_argv): conventional launch command + task flag.
    entrypoint: List[str] = field(default_factory=list)
    task_arg: Optional[str] = None

    def session_env(self, gateway_url: str, mcp_url: str) -> Dict[str, str]:
        """Environment for the forwarded exec: gateway-routed, provider-scrubbed."""
        router = default_router()
        env: Dict[str, str] = {
            # LLM routing via AgentGateway (centralized in the ModelRouter).
            **router.llm_env(gateway_url),
            "TETHRICOR_MCP_URL": mcp_url,
            # Force the harness to treat execution as remote/forwarded.
            "TETHRICOR_EXECUTION": "forwarded",
        }
        # Explicitly blank any provider key so an inherited one can't leak past the gateway.
        for var in PROVIDER_KEY_VARS:
            env[var] = ""
        env.update(self.extra_env)
        # Router-provided credentials survive the scrub. The default gateway router
        # contributes none; only a local escape-hatch router (e.g. direct Azure OpenAI,
        # used when no AgentGateway is available yet) does.
        env.update(router.secret_env())
        return env


ADAPTERS: Dict[str, HarnessAdapter] = {
    "hermes": Adapter(
        name="hermes",
        default_profile="python312",
        entrypoint=["hermes", "run"],
        task_arg="--task",
        # Hermes-specific hardening: no autonomous messaging, cron, or skill creation,
        # and force its sandbox backend to the enterprise agent-runtime.
        extra_env={
            "HERMES_DISABLE_MESSAGING": "1",
            "HERMES_DISABLE_CRON": "1",
            "HERMES_DISABLE_SKILL_CREATION": "1",
            "HERMES_SANDBOX_BACKEND": "agent-runtime",
        },
    ),
    "pi": Adapter(
        name="pi",
        default_profile="node20",
        entrypoint=["pi", "run"],
        task_arg="--task",
        # Pi drives execution over its JSONL/RPC protocol; force that protocol and point
        # its sandbox/tooling at the enterprise services rather than local exec.
        extra_env={
            "PI_SANDBOX_BACKEND": "agent-runtime",
            "PI_PROTOCOL": "jsonl",
            "PI_RPC_MODE": "1",
        },
    ),
    "openhands": Adapter(
        name="openhands",
        default_profile="python312",
        entrypoint=["python", "-m", "openhands.core.main"],
        task_arg="-t",
        # OpenHands supports several runtimes (Docker/Modal/local); force its remote
        # runtime so all action execution is forwarded to the sandbox provider.
        extra_env={
            "SANDBOX_RUNTIME": "remote",
            "OPENHANDS_RUNTIME": "remote",
            "RUNTIME": "remote",
        },
    ),
    "goose": Adapter(
        name="goose",
        default_profile="rust",
        entrypoint=["goose", "run"],
        task_arg="--text",
        # Goose is MCP-native: route its tool/extension calls at the platform MCP surface.
        extra_env={
            "GOOSE_SANDBOX_BACKEND": "agent-runtime",
            "GOOSE_MCP_TRANSPORT": "sse",
        },
    ),
    "opencode": Adapter(
        name="opencode",
        default_profile="node20",
        entrypoint=["opencode", "run"],
        task_arg=None,
        extra_env={"OPENCODE_SANDBOX_BACKEND": "agent-runtime"},
    ),
}

# Harness type -> adapter name (feynman rides the Pi adapter).
_TYPE_TO_ADAPTER: Dict[str, str] = {
    "hermes": "hermes",
    "pi": "pi",
    "feynman": "pi",
    "openhands": "openhands",
    "goose": "goose",
    "opencode": "opencode",
}


def adapter_for(harness_type: str) -> HarnessAdapter:
    try:
        return ADAPTERS[_TYPE_TO_ADAPTER[harness_type]]
    except KeyError as exc:
        raise KeyError(f"unknown harness type {harness_type!r}") from exc


def register_harness(harness_type: str, adapter: HarnessAdapter) -> None:
    """Register (or override) the adapter for a harness type. Used by plugin discovery."""
    ADAPTERS[adapter.name] = adapter
    _TYPE_TO_ADAPTER[harness_type] = adapter.name


def available_harnesses() -> List[str]:
    return sorted(_TYPE_TO_ADAPTER)
