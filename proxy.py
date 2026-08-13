"""Runpod load-balancer adapter for a local llama-server process."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse


LLAMA_BASE = f"http://127.0.0.1:{os.environ.get('LLAMA_SERVER_PORT', '8080')}"
OUTER_PORT = int(os.environ.get("PORT", "8000"))
PROCESS: subprocess.Popen[bytes] | None = None
CLIENT: httpx.AsyncClient | None = None


def llama_command() -> list[str]:
    return [
        os.environ["LLAMA_SERVER_BIN"],
        "--model", os.environ["LLAMA_MODEL_PATH"],
        "--mmproj", os.environ["LLAMA_MMPROJ_PATH"],
        "--model-draft", os.environ["LLAMA_DRAFT_PATH"],
        "--spec-type", "draft-dflash",
        "--spec-draft-ngl", os.environ.get("LLAMA_DRAFT_N_GPU_LAYERS", "all"),
        "--spec-draft-n-max", os.environ.get("LLAMA_DRAFT_N_MAX", "3"),
        "--gpu-layers", os.environ.get("LLAMA_N_GPU_LAYERS", "all"),
        "--ctx-size", os.environ.get("LLAMA_CONTEXT_SIZE", "131072"),
        "--parallel", os.environ.get("LLAMA_PARALLEL_SLOTS", "1"),
        "--host", "127.0.0.1",
        "--port", os.environ.get("LLAMA_SERVER_PORT", "8080"),
        "--alias", os.environ.get("LLAMA_MODEL_ALIAS", "muse-glimmer-30b"),
        "--jinja", "--reasoning-format", "auto",
        "--reasoning-budget", os.environ.get("LLAMA_REASONING_BUDGET", "-1"),
        "--chat-template-kwargs",
        '{"reasoning_strength":"%s"}' % os.environ.get("LLAMA_REASONING_STRENGTH", "high"),
        "--temp", "1.0", "--top-p", "0.95", "--top-k", "64",
        "--flash-attn", "on", "--metrics", "--no-ui-mcp-proxy",
    ]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global PROCESS, CLIENT
    PROCESS = subprocess.Popen(llama_command())
    CLIENT = httpx.AsyncClient(timeout=None)
    try:
        yield
    finally:
        if CLIENT is not None:
            await CLIENT.aclose()
        if PROCESS is not None and PROCESS.poll() is None:
            PROCESS.send_signal(signal.SIGTERM)
            try:
                await asyncio.to_thread(PROCESS.wait, 30)
            except subprocess.TimeoutExpired:
                PROCESS.kill()


app = FastAPI(lifespan=lifespan)


@app.get("/ping")
async def ping() -> Response:
    """Return 204 while loading and 200 once llama.cpp is healthy."""
    if PROCESS is None or PROCESS.poll() is not None or CLIENT is None:
        return Response(status_code=500)
    try:
        upstream = await CLIENT.get(f"{LLAMA_BASE}/health")
    except httpx.HTTPError:
        return Response(status_code=204)
    return Response(status_code=200 if upstream.status_code == 200 else 204)


def forwarded_headers(request: Request) -> dict[str, str]:
    skip = {"host", "content-length", "connection"}
    return {k: v for k, v in request.headers.items() if k.lower() not in skip}


def is_streaming(request: Request, body: bytes) -> bool:
    if "text/event-stream" in request.headers.get("accept", ""):
        return True
    try:
        return bool(json.loads(body).get("stream", False))
    except (ValueError, AttributeError):
        return False


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def forward(path: str, request: Request) -> Response | StreamingResponse:
    if path == "ping":
        return await ping()
    if CLIENT is None:
        return Response(status_code=503, content=b"worker is starting")
    body = await request.body()
    headers = forwarded_headers(request)
    url = f"{LLAMA_BASE}/{path}"
    if is_streaming(request, body):
        async def stream() -> AsyncIterator[bytes]:
            assert CLIENT is not None
            async with CLIENT.stream(request.method, url, headers=headers, content=body) as upstream:
                async for chunk in upstream.aiter_raw():
                    yield chunk
        return StreamingResponse(stream(), media_type="text/event-stream")
    upstream = await CLIENT.request(request.method, url, headers=headers, content=body)
    response_headers = {
        k: v for k, v in upstream.headers.items()
        if k.lower() not in {"content-length", "transfer-encoding", "connection"}
    }
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
        media_type=upstream.headers.get("content-type"),
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=OUTER_PORT)
