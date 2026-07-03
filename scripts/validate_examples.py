"""Validate example harness.yaml files against the JSON schema.

Usage: python scripts/validate_examples.py
"""
from __future__ import annotations

import json
import pathlib
import sys

import yaml
from jsonschema import Draft202012Validator

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "schemas" / "harness-config-schema.json"
EXAMPLES_DIR = ROOT / "examples"


def main() -> int:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)

    examples = sorted(EXAMPLES_DIR.glob("harness.*.yaml"))
    if not examples:
        print("no example files found", file=sys.stderr)
        return 1

    failures = 0
    for path in examples:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
        if errors:
            failures += 1
            print(f"FAIL {path.name}")
            for err in errors:
                loc = "/".join(str(p) for p in err.path) or "<root>"
                print(f"  - {loc}: {err.message}")
        else:
            print(f"OK   {path.name}")

    print(f"\n{len(examples) - failures}/{len(examples)} valid")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
