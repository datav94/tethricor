"""tethricor — the plug-and-play SDK for the Tethricor framework.

Import and go. `sandbox` is required -- there is no default sandbox provider, you must
say what to run against (e.g. `remote-runtime` pointed at a service you trust, or an
installed provider like `microsandbox`/`e2b`):

    from tethricor import Harness
    result = Harness("hermes", model="gpt-4o-standard", sandbox="remote-runtime", source="https://...").run([...])

Harnesses, sandbox backends, and model routers are swappable providers discovered from
Python entry points (see `tethricor.discovery`). This SDK is a thin facade over `tethricor_runtime`.
"""
from __future__ import annotations

from tethricor_runtime.observability import Callbacks

from .direct_azure import AzureOpenAIRouter, use_direct_azure_openai
from .discovery import load_plugins
from .harness import Harness
from .types import Event, SandboxSession, TaskResult

__all__ = [
    "Harness",
    "Event",
    "TaskResult",
    "SandboxSession",
    "Callbacks",
    "load_plugins",
    # Local-only convenience for running without an AgentGateway (see direct_azure).
    "use_direct_azure_openai",
    "AzureOpenAIRouter",
    "__version__",
]

__version__ = "0.1.0"

# Register any installed third-party provider packages at import time (idempotent).
load_plugins()
