"""mock-mcp — a minimal Model Context Protocol stand-in for local parity.

Serves a couple of dummy tools over a small JSON-RPC-style HTTP surface plus an SSE
stream. This is NOT a full MCP implementation; in production the harness reaches the
real enterprise MCP through AgentGateway. It exists so the local docker-compose bundle
has something to point `TETHRICOR_MCP_URL` at.
"""
from __future__ import annotations

import asyncio
import json
import os

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI(title="mock-mcp")

TOOLS = [
    {
        "name": "echo",
        "description": "Echo back the provided text.",
        "inputSchema": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
    {
        "name": "get_time",
        "description": "Return a fixed dummy timestamp.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/tools")
def list_tools():
    return {"tools": TOOLS}


@app.post("/rpc")
async def rpc(request: Request):
    """Tiny JSON-RPC handler supporting `tools/list` and `tools/call`."""
    body = await request.json()
    method = body.get("method")
    req_id = body.get("id")

    if method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = body.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})
        if name == "echo":
            result = {"content": [{"type": "text", "text": args.get("text", "")}]}
        elif name == "get_time":
            result = {"content": [{"type": "text", "text": "2026-01-01T00:00:00Z"}]}
        else:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"unknown tool {name!r}"}}
    else:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"unknown method {method!r}"}}

    return {"jsonrpc": "2.0", "id": req_id, "result": result}


@app.get("/sse")
async def sse():
    """Minimal SSE endpoint announcing tool availability once, then keep-alive."""
    async def stream():
        yield f"data: {json.dumps({'type': 'tools', 'tools': [t['name'] for t in TOOLS]})}\n\n"
        while True:
            await asyncio.sleep(15)
            yield "data: {\"type\": \"ping\"}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "9090")))
