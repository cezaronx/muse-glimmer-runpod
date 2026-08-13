"""Local OpenAI-compatible router for the Muse Glimmer Pod and Serverless endpoint."""

from __future__ import annotations

import hmac
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from runpod_discovery import DiscoveryError, PodConnection, discovery_from_environment
from ssh_tunnel import TunnelError, PodSSHTunnel, tunnel_from_environment


logger = logging.getLogger("muse.gateway")


SERVERLESS_BASE = os.getenv(
    "SERVERLESS_BASE_URL", "https://80ooydmc06vh70.api.runpod.ai"
).rstrip("/")
RUNPOD_KEY = os.getenv("RUNPOD_API_KEY") or os.getenv("RUNPOD_KEY", "")
DEFAULT_BACKEND = os.getenv("BACKEND_MODE", "auto").lower()
GATEWAY_TOKEN = os.getenv("GATEWAY_TOKEN", "")
POD_HEALTH_TIMEOUT = float(os.getenv("POD_HEALTH_TIMEOUT_SECONDS", "3"))
OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://windows.tail9a46d1.ts.net:11434").rstrip("/")
MODEL_REGISTRY = {
    "qwen3.5:9b": {"policy": "ollama", "base_url": OLLAMA_BASE},
    "muse-glimmer-30b": {"policy": "muse", "base_url": None},
}


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    app.state.client = httpx.AsyncClient(timeout=None)
    app.state.pod_tunnel = tunnel_from_environment()
    try:
        yield
    finally:
        await app.state.pod_tunnel.close()
        await app.state.client.aclose()


app = FastAPI(title="Muse Glimmer local gateway", lifespan=lifespan)
FRONTEND_HTML = Path(__file__).with_name("index.html").read_text(encoding="utf-8")


@app.get("/")
async def root() -> HTMLResponse:
    return HTMLResponse(FRONTEND_HTML)


def require_local_token(request: Request) -> Response | None:
    if not GATEWAY_TOKEN:
        return None
    supplied = request.headers.get("authorization", "")
    expected = f"Bearer {GATEWAY_TOKEN}"
    if not hmac.compare_digest(supplied, expected):
        return JSONResponse({"error": "gateway authentication required"}, status_code=401)
    return None


def requested_backend(request: Request) -> str:
    backend = request.headers.get("x-muse-backend", DEFAULT_BACKEND).lower()
    if backend not in {"auto", "pod", "serverless", "ollama"}:
        raise ValueError("X-Muse-Backend must be auto, pod, serverless, or ollama")
    return backend


async def ping(
    client: httpx.AsyncClient,
    base_url: str,
    headers: dict[str, str],
    path: str = "/ping",
) -> bool:
    try:
        response = await client.get(f"{base_url}{path}", headers=headers, timeout=POD_HEALTH_TIMEOUT)
        # Runpod's custom worker proxy returns 204 while llama.cpp is still
        # loading and 200 only after the model health endpoint is ready.
        return response.status_code == 200
    except httpx.HTTPError:
        return False


async def resolve_target(
    request: Request, model_id: str
) -> tuple[str, str, dict[str, str], dict[str, object]]:
    registration = MODEL_REGISTRY[model_id]
    mode = requested_backend(request)
    client: httpx.AsyncClient = app.state.client
    serverless_headers = {"Authorization": f"Bearer {RUNPOD_KEY}"}

    if registration["policy"] == "ollama":
        if mode != "auto" and mode != "ollama":
            raise ValueError(f"Model {model_id} is pinned to the Ollama backend")
        ollama_base = str(registration["base_url"])
        if not await ping(client, ollama_base, {}, "/api/tags"):
            raise RuntimeError("Windows Ollama is unavailable over the configured private route")
        # Ollama's OpenAI-compatible endpoint accepts this placeholder token;
        # it is not a gateway or RunPod credential.
        return ollama_base, "ollama", {"Authorization": "Bearer ollama"}, {"model": model_id, "transport": "tailscale"}

    pod_info: PodConnection | None = None
    pod_error: str | None = None
    tunnel: PodSSHTunnel = app.state.pod_tunnel

    if mode in {"auto", "pod"}:
        try:
            pod_info = discovery_from_environment().discover()
            if pod_info:
                tunnel_error: str | None = None
                try:
                    tunnel_url = await tunnel.ensure(pod_info)
                    if await ping(client, tunnel_url, {}):
                        return tunnel_url, "pod", {}, {**pod_info.as_dict(), "transport": "ssh-tunnel"}
                except TunnelError as exc:
                    tunnel_error = str(exc)
                # The Runpod HTTP proxy is the fallback for Pods whose
                # template did not provide a usable SSH public key. It is
                # still addressed only through the local gateway.
                if pod_info.base_url and await ping(client, pod_info.base_url, {}):
                    return pod_info.base_url, "pod", {}, {**pod_info.as_dict(), "transport": "runpod-http-proxy"}
                if tunnel_error:
                    pod_error = tunnel_error
        except (DiscoveryError, TunnelError, ValueError) as exc:
            pod_error = str(exc)
        if mode == "pod":
            raise RuntimeError(pod_error or "No healthy manually started Pod found")

    # Do not preflight Serverless with /ping. A load-balancing endpoint can
    # legitimately have zero warm workers before a request arrives; probing
    # /ping in that state rejects the request locally and prevents Runpod from
    # ever receiving the request that would trigger worker allocation. Send
    # the real OpenAI-compatible request and let Runpod report capacity or
    # worker errors directly.
    return SERVERLESS_BASE, "serverless", serverless_headers, {
        "model": model_id,
        "pod": pod_info.as_dict() if pod_info else None,
        "pod_error": pod_error,
        "preflight": "skipped",
    }


@app.get("/healthz")
async def healthz(request: Request) -> JSONResponse:
    denied = require_local_token(request)
    if denied:
        return denied  # type: ignore[return-value]
    try:
        _, backend, _, detail = await resolve_target(request, "muse-glimmer-30b")
        return JSONResponse({"ready": True, "backend": backend, "detail": detail})
    except (RuntimeError, ValueError) as exc:
        return JSONResponse({"ready": False, "error": str(exc)}, status_code=503)


@app.get("/backends")
async def backends(request: Request) -> JSONResponse:
    denied = require_local_token(request)
    if denied:
        return denied  # type: ignore[return-value]
    discovery = discovery_from_environment()
    pod: dict[str, object] = {"available": False}
    try:
        connection = discovery.discover()
        if connection:
            pod = {"available": True, **connection.as_dict()}
    except (DiscoveryError, TunnelError, ValueError) as exc:
        pod["error"] = str(exc)
    return JSONResponse(
        {
            "default": DEFAULT_BACKEND,
            "models": {
                model_id: {"policy": item["policy"]}
                for model_id, item in MODEL_REGISTRY.items()
            },
            "serverless": {"base_url": SERVERLESS_BASE},
            "pod": pod,
            "mutations_enabled": False,
        }
    )


@app.get("/v1/models")
async def models(request: Request) -> JSONResponse:
    denied = require_local_token(request)
    if denied:
        return denied  # type: ignore[return-value]
    now = int(time.time())
    return JSONResponse(
        {
            "object": "list",
            "data": [
                {
                    "id": model_id,
                    "object": "model",
                    "created": now,
                    "owned_by": "ai-security-lab",
                }
                for model_id in MODEL_REGISTRY
            ],
        }
    )


def model_from_body(path: str, body: bytes) -> str | None:
    if not path.startswith("v1/") or path == "v1/models":
        return None
    try:
        payload = json.loads(body or b"{}")
    except (TypeError, ValueError):
        return None
    model_id = payload.get("model") if isinstance(payload, dict) else None
    return str(model_id) if model_id else None


def provenance_headers(model_id: str, backend: str, request_id: str, fallback: bool = False) -> dict[str, str]:
    headers = {
        "X-Muse-Model": model_id,
        "X-Muse-Backend": backend,
        "X-Muse-Request-Id": request_id,
    }
    if fallback:
        headers["X-Muse-Fallback"] = "true"
    return headers


def log_request(
    *, request_id: str, model_id: str, backend: str, status: int, started: float,
    fallback: bool = False
) -> None:
    logger.info(
        json.dumps(
            {
                "event": "completion",
                "request_id": request_id,
                "model": model_id,
                "backend": backend,
                "fallback": fallback,
                "status": status,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            },
            separators=(",", ":"),
        )
    )


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
)
async def proxy(path: str, request: Request):
    denied = require_local_token(request)
    if denied:
        return denied
    body = await request.body()
    model_id = model_from_body(path, body)
    if path.startswith("v1/") and path != "v1/models" and not model_id:
        return JSONResponse({"error": {"message": "request must include a stable model id", "type": "invalid_request_error"}}, status_code=400)
    if model_id not in MODEL_REGISTRY:
        return JSONResponse({"error": {"message": f"unknown model: {model_id}", "type": "model_not_found"}}, status_code=404)
    request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
    started = time.perf_counter()
    try:
        base_url, backend, upstream_auth, detail = await resolve_target(request, model_id)
    except (RuntimeError, ValueError) as exc:
        return JSONResponse(
            {"error": str(exc)},
            status_code=503,
            headers=provenance_headers(model_id, "unavailable", request_id),
        )

    fallback = backend == "serverless" and bool(detail.get("pod_error"))
    # Do not relay browser or reverse-proxy headers to the model server. In
    # particular, X-Forwarded-* and Origin describe the gateway hop, not the
    # Ollama request, and some Ollama deployments reject those requests.
    headers = {
        "content-type": request.headers.get("content-type", "application/json"),
        "accept": request.headers.get("accept", "application/json"),
    }
    headers.update(upstream_auth)
    url = f"{base_url}/{path}"
    if request.query_params:
        url += f"?{request.query_params}"
    client: httpx.AsyncClient = app.state.client
    stream_requested = request.headers.get("accept", "").find("text/event-stream") >= 0
    if not stream_requested:
        try:
            upstream = await client.request(request.method, url, headers=headers, content=body)
        except httpx.HTTPError as exc:
            log_request(request_id=request_id, model_id=model_id, backend=backend, status=502,
                        started=started, fallback=fallback)
            return JSONResponse({"error": f"{backend} request failed: {exc}"}, status_code=502)
        response_headers = {
            key: value
            for key, value in upstream.headers.items()
            if key.lower() not in {"content-length", "transfer-encoding", "connection"}
        }
        output = Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=response_headers,
            media_type=upstream.headers.get("content-type"),
        )
        output.headers.update(provenance_headers(model_id, backend, request_id, fallback))
        log_request(request_id=request_id, model_id=model_id, backend=backend,
                    status=upstream.status_code, started=started, fallback=fallback)
        return output

    async def stream() -> AsyncIterator[bytes]:
        async with client.stream(request.method, url, headers=headers, content=body) as upstream:
            async for chunk in upstream.aiter_raw():
                yield chunk

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers=provenance_headers(model_id, backend, request_id, fallback),
    )

