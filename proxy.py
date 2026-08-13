"""Runpod load-balancer adapter for a local llama-server process."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import StreamingResponse


LOGGER = logging.getLogger("muse.worker")
LLAMA_BASE = f"http://127.0.0.1:{os.environ.get('LLAMA_SERVER_PORT', '8080')}"
OUTER_PORT = int(os.environ.get("PORT", "8000"))
PROCESS: subprocess.Popen[bytes] | None = None
CLIENT: httpx.AsyncClient | None = None
PROCESS_WATCHER: asyncio.Task[None] | None = None
STARTUP_WATCHER: asyncio.Task[None] | None = None


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
        # Keep the image hardware-agnostic. Deployment profiles should set
        # LLAMA_CONTEXT_SIZE/CONTEXT_SIZE explicitly for their GPU budget.
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
    global PROCESS, CLIENT, PROCESS_WATCHER, STARTUP_WATCHER
    PROCESS = subprocess.Popen(llama_command())
    CLIENT = httpx.AsyncClient(timeout=None)

    async def stop_worker(message: str) -> None:
        LOGGER.error(message)
        if PROCESS is not None and PROCESS.poll() is None:
            PROCESS.terminate()
            try:
                await asyncio.to_thread(PROCESS.wait, 10)
            except subprocess.TimeoutExpired:
                PROCESS.kill()

    async def watch_process() -> None:
        assert PROCESS is not None
        return_code = await asyncio.to_thread(PROCESS.wait)
        LOGGER.error("llama-server exited with return code %s; worker is unhealthy", return_code)
        # Let Runpod mark this worker unhealthy instead of keeping a proxy
        # alive with no model behind it.
        os.kill(os.getpid(), signal.SIGTERM)

    async def watch_startup() -> None:
        timeout = float(os.environ.get("MODEL_LOAD_TIMEOUT_SECONDS", "600"))
        deadline = asyncio.get_running_loop().time() + timeout
        while PROCESS is not None and PROCESS.poll() is None:
            if asyncio.get_running_loop().time() >= deadline:
                await stop_worker(
                    f"llama-server did not become healthy within {timeout:.0f} seconds"
                )
                return
            await asyncio.sleep(2)

    PROCESS_WATCHER = asyncio.create_task(watch_process())
    STARTUP_WATCHER = asyncio.create_task(watch_startup())
    try:
        yield
    finally:
        if PROCESS_WATCHER is not None:
            PROCESS_WATCHER.cancel()
        if STARTUP_WATCHER is not None:
            STARTUP_WATCHER.cancel()
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
        return Response(status_code=503, content=b"llama-server is not running")
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
async def forward(path: str, request: Request):
    if path == "ping":
        return await ping()
    if PROCESS is None or PROCESS.poll() is not None or CLIENT is None:
        return Response(status_code=503, content=b"llama-server is not running")
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
    try:
        upstream = await CLIENT.request(request.method, url, headers=headers, content=body)
    except httpx.HTTPError as exc:
        LOGGER.error("llama-server request failed: %s", exc)
        return Response(status_code=503, content=b"llama-server is unavailable")
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
