"""Public, typed result/event/session models for the tethricor SDK.

Thin typed views over the shim's contract dicts — no logic, just ergonomics for callers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass(frozen=True)
class Event:
    """One SSE frame from the runtime exec stream."""

    type: str  # stdout | stderr | exit | error
    data: Optional[str] = None
    code: Optional[int] = None

    @classmethod
    def from_dict(cls, raw: dict) -> "Event":
        return cls(type=raw.get("type", ""), data=raw.get("data"), code=raw.get("code"))


@dataclass(frozen=True)
class SandboxSession:
    """A created sandbox session."""

    id: str
    profile: str
    state: str

    @classmethod
    def from_dict(cls, raw: dict) -> "SandboxSession":
        return cls(id=raw.get("id", ""), profile=raw.get("profile", ""), state=raw.get("state", ""))


@dataclass
class TaskResult:
    """Result of running one task through a harness."""

    session_id: str
    exit_code: Optional[int]
    artifact_path: Optional[str]
    events: List[Event] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0
