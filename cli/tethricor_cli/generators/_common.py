"""Shared helpers for artifact generators."""
from __future__ import annotations

from typing import Dict, List

import yaml

RUNTIME_SERVICE = "agent-runtime"
GATEWAY_SERVICE = "agentgateway"


def dump_yaml(obj: object) -> str:
    return yaml.safe_dump(obj, sort_keys=False, default_flow_style=False)


def dump_yaml_docs(docs: List[object]) -> str:
    return "---\n".join(dump_yaml(d) for d in docs)


def sidecar_env(config: dict, *, runtime_url: str, mcp_url: str, gateway_url: str) -> Dict[str, str]:
    """Environment the harness sidecar/shim consumes.

    The shim uses these to forward execution to the agent-runtime and route LLM/MCP
    through AgentGateway. Provider credentials are NOT injected here.
    """
    model = config.get("model", {})
    source = config.get("source", {})
    runtime = config.get("runtime", {})
    env: Dict[str, str] = {
        "TETHRICOR_HARNESS_TYPE": config["harness"]["type"],
        "TETHRICOR_HARNESS_VERSION": str(config["harness"]["version"]),
        "TETHRICOR_RUNTIME_URL": runtime_url,
        "TETHRICOR_RUNTIME_PROFILE": runtime.get("profile", ""),
        "TETHRICOR_RUNTIME_TIMEOUT_SECONDS": str(runtime.get("timeout_seconds", 600)),
        "TETHRICOR_MCP_URL": mcp_url,
        "TETHRICOR_GATEWAY_URL": gateway_url,
        "TETHRICOR_ROUTING_PROFILE": model.get("routing_profile", ""),
        "TETHRICOR_SOURCE_REPO_URL": source.get("repo_url", ""),
        "TETHRICOR_SOURCE_REF": source.get("ref", "main"),
        "TETHRICOR_OUTPUT_MODE": config.get("output", {}).get("mode", "zip-download"),
        "TETHRICOR_SKILLS": ",".join(config.get("skills", [])),
        "TETHRICOR_MCP_SERVERS": ",".join(config.get("mcp", {}).get("servers", [])),
    }
    # Local-only escape hatch (already stripped for non-local targets by security.py).
    direct = model.get("direct_azure_openai")
    if direct:
        env["AZURE_OPENAI_ENDPOINT"] = direct.get("endpoint", "")
        env["AZURE_OPENAI_DEPLOYMENT"] = direct.get("deployment", "")
        if direct.get("api_version"):
            env["AZURE_OPENAI_API_VERSION"] = direct["api_version"]
    return env
