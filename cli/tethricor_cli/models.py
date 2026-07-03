"""Pydantic models mirroring schemas/harness-config-schema.json.

These give ergonomic construction/prompting. The emitted config is still validated
against the JSON schema (the contract source of truth) before it is written.
"""
from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# Not a closed set: built-ins are hermes/pi/feynman/openhands/goose/opencode, but any
# name registered as a HarnessAdapter (entry-point plugin or register_harness) is also
# valid. Kept as `str` rather than a Literal so custom adapters don't need a code change
# here; the actual validity check happens dynamically against the installed registry
# (see cli.py's _available_harness_types()).
HarnessType = str
OutputMode = Literal["zip-download", "stdout-changed-files"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DirectAzureOpenAI(_Strict):
    endpoint: str
    deployment: str
    api_version: Optional[str] = None


class Harness(_Strict):
    type: HarnessType
    version: str


class Model(_Strict):
    # `protected_namespaces=()` silences pydantic's warning about a field named `model`
    # colliding with the reserved `model_` prefix.
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    routing_profile: str
    direct_azure_openai: Optional[DirectAzureOpenAI] = None


class Mcp(_Strict):
    servers: List[str] = Field(default_factory=list)


class Runtime(_Strict):
    profile: str
    timeout_seconds: int = 600
    provider: Optional[str] = None


class Source(_Strict):
    repo_url: str
    ref: str = "main"


class Output(_Strict):
    mode: OutputMode = "zip-download"


class HarnessConfig(_Strict):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    apiVersion: Literal["tethricor.enterprise/v1"] = "tethricor.enterprise/v1"
    kind: Literal["HarnessConfig"] = "HarnessConfig"
    harness: Harness
    model: Model
    skills: List[str] = Field(default_factory=list)
    mcp: Mcp = Field(default_factory=Mcp)
    runtime: Runtime
    source: Source
    output: Output = Field(default_factory=Output)

    def to_ordered_dict(self) -> dict:
        """Serialize preserving field order and dropping unset optionals."""
        return self.model_dump(exclude_none=True)
