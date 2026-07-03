"""tethricor-sandbox-microsandbox — a pluggable SandboxProvider for microsandbox.

Registered via the `tethricor.sandboxes` entry point as `microsandbox`; select it with
`runtime.provider: microsandbox` (or `tethricor init --sandbox microsandbox`).
Endpoint/credentials are platform-injected via env, never in harness.yaml.
"""
from __future__ import annotations

import os
from typing import Optional

import httpx

from tethricor_runtime.interfaces import SandboxProvider

from ._provider import MicrosandboxProvider

__all__ = ["MicrosandboxProvider", "make_provider"]

__version__ = "0.1.0"


def make_provider(*, base_url: str = "", client: Optional[httpx.Client] = None, **_) -> SandboxProvider:
    """Entry-point factory (matches the tethricor.sandboxes registry contract)."""
    return MicrosandboxProvider(
        base_url=base_url or os.environ.get("MICROSANDBOX_URL", "http://127.0.0.1:5555"),
        api_key=os.environ.get("MICROSANDBOX_API_KEY"),
        client=client,
    )
