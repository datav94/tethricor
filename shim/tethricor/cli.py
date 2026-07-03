"""Task-runner entry point (the sidecar CMD), implemented over the tethricor SDK.

`tethricor_runtime.__main__` delegates here so there is a single code path (.cursorrules #6).
"""
from __future__ import annotations

import json
import sys
from typing import List, Optional

from tethricor_runtime.adapters import adapter_for
from tethricor_runtime.config import Settings
from tethricor_runtime.interfaces import RuntimeError_, SessionExpired

from .harness import Harness


def _posture(settings: Settings) -> None:
    adapter = adapter_for(settings.harness_type) if settings.harness_type else None
    info = {
        "harnessType": settings.harness_type,
        "adapter": adapter.name if adapter else None,
        "sandbox": settings.provider,
        "profile": settings.profile or (adapter.default_profile if adapter else None),
        "runtimeUrl": settings.runtime_url,
        "gatewayUrl": settings.gateway_url,
        "mcpUrl": settings.mcp_url,
        "repoUrl": settings.repo_url or None,
        "execution": "forwarded-to-sandbox (no local execution)",
    }
    print(json.dumps(info, indent=2))


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--":
        argv = argv[1:]

    settings = Settings.from_env()

    if not argv:
        _posture(settings)
        return 0

    if not settings.harness_type:
        print("TETHRICOR_HARNESS_TYPE / harness.yaml not resolved; cannot run task", file=sys.stderr)
        return 2

    harness = Harness.from_settings(settings)
    try:
        result = harness.run(argv, stream=True)
    except SessionExpired as exc:
        print(f"session expired: {exc}", file=sys.stderr)
        return 3
    except RuntimeError_ as exc:
        print(f"runtime error: {exc}", file=sys.stderr)
        return 4

    if result.artifact_path:
        print(f"[artifact] wrote {result.artifact_path}", file=sys.stderr)
    return result.exit_code if isinstance(result.exit_code, int) else 0
