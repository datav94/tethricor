"""Shim settings: resolved from the mounted harness.yaml + injected environment."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

import yaml

# Default in-cluster service endpoints; shared by env loading and the SDK facade.
DEFAULT_RUNTIME_URL = "http://agent-runtime:8080"
DEFAULT_GATEWAY_URL = "http://agentgateway:8080"
DEFAULT_MCP_URL = "http://agentgateway:8080/mcp"
# Fallback ONLY for Settings.provider below, when a hand-written harness.yaml omits
# runtime.provider. Not an endorsement or recommendation -- remote-runtime is just the
# always-installed generic REST client; what it actually does depends entirely on what
# TETHRICOR_RUNTIME_URL points at. CLI-generated configs always set provider explicitly
# (tethricor init requires --sandbox), so this fallback rarely triggers in practice.
DEFAULT_PROVIDER = "remote-runtime"


@dataclass
class Settings:
    harness_type: str
    runtime_url: str
    gateway_url: str
    mcp_url: str
    config_path: str = ""
    config: Dict = field(default_factory=dict)

    @property
    def profile(self) -> str:
        return (self.config.get("runtime", {}) or {}).get("profile", "")

    @property
    def provider(self) -> str:
        return (self.config.get("runtime", {}) or {}).get("provider") or DEFAULT_PROVIDER

    @property
    def timeout_seconds(self) -> int:
        return int((self.config.get("runtime", {}) or {}).get("timeout_seconds", 600))

    @property
    def repo_url(self) -> str:
        return (self.config.get("source", {}) or {}).get("repo_url", "")

    @property
    def ref(self) -> str:
        return (self.config.get("source", {}) or {}).get("ref", "")

    @classmethod
    def from_env(cls) -> "Settings":
        config_path = os.environ.get("TETHRICOR_CONFIG_PATH", "/etc/tethricor/harness.yaml")
        config: Dict = {}
        p = Path(config_path)
        if p.exists():
            config = yaml.safe_load(p.read_text(encoding="utf-8")) or {}

        harness_type = os.environ.get("TETHRICOR_HARNESS_TYPE") or config.get("harness", {}).get("type", "")
        return cls(
            harness_type=harness_type,
            runtime_url=os.environ.get("TETHRICOR_RUNTIME_URL", DEFAULT_RUNTIME_URL),
            gateway_url=os.environ.get("TETHRICOR_GATEWAY_URL", DEFAULT_GATEWAY_URL),
            mcp_url=os.environ.get("TETHRICOR_MCP_URL", DEFAULT_MCP_URL),
            config_path=config_path,
            config=config,
        )
