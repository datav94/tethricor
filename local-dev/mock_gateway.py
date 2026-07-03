"""mock-gateway — a local OpenAI-compatible stand-in for your LLM gateway.

In production, the harness routes all LLM traffic through your organization's LLM
gateway (.cursorrules #2) -- any OpenAI-compatible endpoint (a self-hosted LiteLLM
proxy, Portkey, Kong AI Gateway, Azure APIM, etc.) works, not a specific vendor. For
local parity this tiny echo server exposes the OpenAI-compatible surface the shim
adapters point at (`OPENAI_BASE_URL`/`ANTHROPIC_BASE_URL`), so a real harness can be
exercised end-to-end offline. It does NOT call any real model — it echoes the last user
message back as the assistant reply.

This is a TEST DOUBLE only; never use it as a real gateway.
"""
from __future__ import annotations

import os
import time
import uuid

import uvicorn
from fastapi import FastAPI, Request

app = FastAPI(title="mock-gateway (AgentGateway double)")

MODELS = ["gpt-4o-standard", "gpt-4o-mini", "claude-3-5-sonnet"]


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/v1/models")
def list_models():
    return {"object": "list", "data": [{"id": m, "object": "model", "owned_by": "mock-gateway"} for m in MODELS]}


def _last_user_text(messages: list[dict]) -> str:
    for msg in reversed(messages or []):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):  # OpenAI content-parts form
                return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
            return str(content)
    return ""


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    prompt = _last_user_text(body.get("messages", []))
    reply = f"[mock-gateway echo] {prompt}".strip()
    now = int(time.time())
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": now,
        "model": body.get("model", MODELS[0]),
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": reply},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": len(prompt.split()), "completion_tokens": len(reply.split()), "total_tokens": 0},
    }


@app.post("/v1/completions")
async def completions(request: Request):
    body = await request.json()
    prompt = body.get("prompt", "")
    if isinstance(prompt, list):
        prompt = " ".join(map(str, prompt))
    return {
        "id": f"cmpl-{uuid.uuid4().hex[:12]}",
        "object": "text_completion",
        "created": int(time.time()),
        "model": body.get("model", MODELS[0]),
        "choices": [{"index": 0, "text": f"[mock-gateway echo] {prompt}", "finish_reason": "stop"}],
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8081")))
