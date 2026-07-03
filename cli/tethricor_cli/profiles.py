"""Harness metadata: adapter mapping and default runtime profiles.

`pi` and `feynman` share the Pi adapter (Feynman = Pi + research profile).
Default runtime profiles map to agent-runtime toolchains (DESIGN_NOTES A1).
"""
from __future__ import annotations

from typing import Dict, List

HARNESSES: Dict[str, Dict[str, str]] = {
    "hermes": {"adapter": "hermes", "default_profile": "python312"},
    "pi": {"adapter": "pi", "default_profile": "node20"},
    "feynman": {"adapter": "pi", "default_profile": "node20"},
    "openhands": {"adapter": "openhands", "default_profile": "python312"},
    "goose": {"adapter": "goose", "default_profile": "rust"},
    "opencode": {"adapter": "opencode", "default_profile": "node20"},
}

# Advertised runtime profiles (agent-runtime GET /v1/profiles + the language profiles
# we depend on upstream). The CLI validates against the live endpoint when available;
# this list is the offline fallback for `init`.
KNOWN_RUNTIME_PROFILES: List[str] = [
    "minimal",
    "skills-minimal",
    "git",
    "node20",
    "skill-security-runner",
    "python312",
    "rust",
    "go",
    "polyglot-dev",
]


def known_types() -> List[str]:
    return list(HARNESSES)


def default_profile(harness_type: str) -> str:
    return HARNESSES[harness_type]["default_profile"]


def adapter_for(harness_type: str) -> str:
    return HARNESSES[harness_type]["adapter"]
