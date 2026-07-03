"""Locate and validate against the Phase-1 JSON schema (the contract source of truth)."""
from __future__ import annotations

import json
import os
import pathlib
from typing import List

from jsonschema import Draft202012Validator

_SCHEMA_REL = pathlib.Path("schemas") / "harness-config-schema.json"


def find_schema_path() -> pathlib.Path:
    """Resolve the schema path.

    Order: TETHRICOR_SCHEMA_PATH env override, then walk upward from CWD and from this
    package looking for schemas/harness-config-schema.json.
    """
    override = os.environ.get("TETHRICOR_SCHEMA_PATH")
    if override:
        p = pathlib.Path(override)
        if p.is_file():
            return p
        raise FileNotFoundError(f"TETHRICOR_SCHEMA_PATH does not point to a file: {override}")

    starts = [pathlib.Path.cwd(), pathlib.Path(__file__).resolve().parent]
    for start in starts:
        for base in [start, *start.parents]:
            candidate = base / _SCHEMA_REL
            if candidate.is_file():
                return candidate
    raise FileNotFoundError(
        "Could not locate schemas/harness-config-schema.json. "
        "Set TETHRICOR_SCHEMA_PATH to override."
    )


def load_validator() -> Draft202012Validator:
    schema = json.loads(find_schema_path().read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def validation_errors(data: dict) -> List[str]:
    """Return human-readable schema violations (empty list == valid)."""
    validator = load_validator()
    out: List[str] = []
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        loc = "/".join(str(p) for p in err.path) or "<root>"
        out.append(f"{loc}: {err.message}")
    return out
