"""Tethricor execution shim.

The shim is the enforcement point for `.cursorrules` #1/#2: the harness NEVER runs
code, bash, or terminal commands locally. Every execution is forwarded to the
enterprise agent-runtime over its REST/SSE contract, and every LLM/MCP call is routed
through AgentGateway. See docs/agent_context/DESIGN_NOTES.md §7 for the runtime contract.
"""
from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
