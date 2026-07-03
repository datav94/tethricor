"""tethricor-sandbox-e2b — a pluggable SandboxProvider for E2B (Firecracker microVMs).

Registered via the `tethricor.sandboxes` entry point as `e2b`; select with
`runtime.provider: e2b` (or `tethricor init --sandbox e2b`). The E2B SDK is an
optional extra (`pip install 'tethricor-sandbox-e2b[sdk]'`); the API key is platform-injected
via `E2B_API_KEY`, never in harness.yaml.
"""
from __future__ import annotations

import os
from typing import Optional

from tethricor_runtime.interfaces import SandboxProvider

from ._provider import E2BProvider, E2BSandboxClient, ExecOutput

__all__ = ["E2BProvider", "E2BSandboxClient", "ExecOutput", "make_provider"]

__version__ = "0.1.0"


def make_provider(*, base_url: str = "", client: Optional[object] = None, **_) -> SandboxProvider:
    """Entry-point factory.

    Builds the provider over the real E2B SDK binding (constructed lazily so the SDK is
    only imported when a session actually starts). Tests inject a fake seam by
    constructing `E2BProvider(seam)` directly.
    """
    from ._sdk import E2BSdkClient

    return E2BProvider(E2BSdkClient(api_key=os.environ.get("E2B_API_KEY")))
