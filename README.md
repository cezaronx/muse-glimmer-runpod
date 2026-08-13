# Meta Muse Glimmer 30B Runpod Serverless worker

[![Publish worker image](https://github.com/cezaronx/muse-glimmer-runpod/actions/workflows/publish-image.yml/badge.svg)](https://github.com/cezaronx/muse-glimmer-runpod/actions/workflows/publish-image.yml)

Public reference implementation for serving Meta Muse Glimmer 30B through a
Runpod Serverless load-balancing endpoint. This repository contains worker
software and deployment documentation only; it does not contain model
weights, Runpod credentials, registry credentials, or private lab data.

This bundle is a CUDA worker for Meta's official Muse Glimmer GGUF release. It
runs `llama-server` directly as a Runpod Serverless load-balancing worker, so
the exposed port is a real OpenAI-compatible HTTP API rather than a queue
wrapper around a custom JSON handler.

## What is pinned

- llama.cpp release `b10375`, built with CUDA. Muse Glimmer support landed in
  llama.cpp before `b10353`; b10375 is the newer release selected for the
  worker.
- Hugging Face repo: `meta-models/Muse-Glimmer-30B-GGUF`.
- Main model: `Muse-Glimmer-30B-KQuant-Dynamic-Q4_K_XL.gguf`.
- Vision projector: `mmproj-Muse-Glimmer-30B-Q4_K_M.gguf`.
- DFlash drafter: `dflash-Muse-Glimmer-30B-Q4_K_M.gguf`.

The startup script downloads all three files to
`/runpod-volume/models/muse-glimmer-30b` and reuses them on later worker
starts. A file lock prevents concurrent first-downloads from racing on the
same volume. The worker fails closed if the network volume is absent unless
`ALLOW_EPHEMERAL_MODEL_CACHE=1` is explicitly set for a disposable test.

## API behavior

`llama-server` provides:

- `GET /health`
- `GET /v1/models`
- `POST /v1/chat/completions`, including SSE when `stream=true`
- OpenAI-style `tools`, `tool_choice`, and parsed `tool_calls`
- multimodal message content using OpenAI image blocks
- `GET /metrics` for Prometheus-compatible metrics

The server is started with `--jinja`, which is required for the model's
embedded chat template and tool-call parsing. Reasoning is returned separately
as `reasoning_content` when the model/template emits it. Muse Glimmer's
reasoning channel is not disabled by this configuration; `REASONING_BUDGET`
and `REASONING_STRENGTH` control its cost.

The worker does not enable llama.cpp's built-in shell/file/MCP tools. Tool
definitions supplied by the client are only model outputs; the AI Security
Lab must execute tools in an explicit policy-controlled sandbox with approval
and audit logging.

Runpod load-balancing health checks use `/ping`; the bundled `proxy.py` owns
that route and returns 204 while llama.cpp is loading and 200 once llama.cpp's
`/health` is ready. All other routes, including streaming, are forwarded to
llama.cpp on an internal port.

## Build locally

From this directory:

```powershell
python .\validate_worker.py
.\build-image.ps1
```

The script builds only; it never pushes an image. Override the local tag or
CUDA targets when needed:

```powershell
.\build-image.ps1 -Repository "ai-security-lab/muse-glimmer-runpod" -Tag "b10375" -CudaArchitectures "86;89;90"
```

For a registry-qualified local tag, set `-Registry` explicitly or use
`CONTAINER_REGISTRY`. The script does not perform registry login.

## Publication workflow

Publication is intentionally a separate, interactive action. First authenticate
to the chosen registry outside this bundle, then run:

```powershell
docker login REGISTRY_HOST
.\publish-image.ps1 -Registry "REGISTRY_HOST" -Repository "NAMESPACE/muse-glimmer-runpod" -Tag "b10375"
```

The publication script requires typing an exact confirmation phrase, builds for
`linux/amd64`, pushes the image, and asks the operator to record the immutable
digest. No registry host, username, token, or password is stored in this
repository. Do not deploy a mutable `latest` tag to Runpod.

The current handoff does not run the publication script. A build-only attempt
was made for validation and stopped before any build work because Docker's
daemon is not accessible in this desktop session. No model download or
inference was attempted.

The image build requires network access to GitHub, Ubuntu packages, and
Hugging Face's Python client. It compiles `llama-server`; it does not download
the 22.7 GB of model artifacts until the worker starts with a mounted volume.

## Read-only local smoke test

The static check is always safe to run:

```powershell
python .\validate_worker.py
```

A real inference smoke test requires a CUDA-capable Linux host and the three
GGUF files. After building the image, mount a disposable directory as
`/runpod-volume`, set `HF_TOKEN` only if needed, and let the container download
the files. Then check `/health`, `/v1/models`, the text payload, and the tool
payload under `test_payloads/`. Do not treat a container startup as proof of
tool-call correctness: inspect that the response contains a structured
`message.tool_calls` array with a JSON string in `function.arguments`.

## Deployment plan; no cloud resources are created by this bundle

1. Select a registry visible to Runpod, authenticate separately, run
   `publish-image.ps1`, and record the resulting image digest; do not deploy by
   mutable `latest`.
2. Create or select one Runpod network volume in the same data center as the
   intended GPU. Budget at least 30 GB for these three files plus cache and
   temporary download space; 50 GB leaves operational headroom.
3. In Runpod, configure a **Serverless load-balancing endpoint** with this
   image, container port `8000`, the network volume mounted at
   `/runpod-volume`, and one worker initially. Use a 24 GB GPU only after the
   dynamic build's actual VRAM and context budget are confirmed; 32 GB is the
   safer starting point for the dynamic quant plus projector and drafter.
4. Set the environment variables from `deployment.env.example`. Keep
   `DOWNLOAD_MODELS=1` for the first worker so it seeds the volume. After the
   three files and `.download-complete` exist, `DOWNLOAD_MODELS=0` is a stricter
   offline mode for subsequent workers.
5. Use the endpoint's health check against `/ping`; the proxy returns 204 while
   loading and 200 when llama.cpp's `/health` is ready. Wait for HTTP 200 before
   sending inference traffic. The first start includes download, model load,
   projector load, and DFlash binding; it can exceed ordinary HTTP client
   timeouts.
6. Point an OpenAI client at
   `https://ENDPOINT_ID.api.runpod.ai/v1` with the Runpod API key as its bearer
   key, and use the model id `muse-glimmer-30b`. Run the text, tool-call,
   streaming, and image probes before increasing workers or concurrency.
7. For the AI Security Lab, keep tool execution outside this container unless
   it is an intentionally isolated simulated target. Add request/response
   logging with secrets and image data redacted, and retain the `/metrics`
   series for latency, errors, and speculative acceptance.

## Public reuse

Forks and derivative workers are welcome. Read `LICENSE`,
`THIRD_PARTY_NOTICES.md`, and the model repository's terms before
redistributing the image or using the model commercially. Never commit API
keys, registry tokens, Hugging Face tokens, cached model files, private volume
details, or request logs containing user data.

See `CONTRIBUTING.md` for changes and `SECURITY.md` for private vulnerability
reports.

## Exact assumptions and risks

- The selected file names are the official names currently listed by Meta's
  GGUF repository. If Meta renames or replaces them, update the three names in
  `start.sh` and `deployment.env.example` together.
- The default selects the higher-quality Dynamic build, not Meta's smaller
  17 GB build. It assumes a single NVIDIA GPU with enough room for roughly
  20 GB of text weights plus projector, drafter, KV cache, and runtime
  overhead. A 24 GB card may need a smaller context or the 17 GB build.
- `DRAFT_N_MAX=3` is a conservative Muse-specific default from llama.cpp
  support work. Tune it only after measuring accepted draft tokens and total
  tokens/second on the chosen GPU.
- Current llama.cpp supports the model architecture and DFlash path, but
  upstream issues around DFlash with multimodal requests and official-GGUF
  metadata have existed. The deployment gate is therefore a real startup
  bind plus text, tool, stream, and image probes on the pinned image; if the
  image probe fails while text works, run the worker in text/tool mode without
  DFlash until an upstream fix is available rather than silently claiming all
  three capabilities.
- Runpod network volumes persist across worker shutdowns, but a network volume
  is data-center-specific and concurrent writers need coordination. Start with
  one worker and seed the volume before scaling out.
- This worker exposes llama.cpp's API directly. It does not add an API key or
  authorization layer inside the container; rely on Runpod endpoint auth and
  place additional policy enforcement in front of any tool-capable deployment.

## Sources checked on 2026-08-13

- Meta model card and official GGUF files:
  <https://huggingface.co/meta-models/Muse-Glimmer-30B-GGUF>
- llama.cpp release b10375:
  <https://github.com/ggml-org/llama.cpp/releases/tag/b10375>
- llama.cpp server API and function calling:
  <https://github.com/ggml-org/llama.cpp/blob/b10375/tools/server/README.md>
- Runpod Serverless worker and load-balancing concepts:
  <https://docs.runpod.io/serverless/workers/handler-functions>
  <https://docs.runpod.io/serverless/endpoints/overview>
- Runpod network volumes:
  <https://docs.runpod.io/storage/network-volumes>
