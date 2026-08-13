# Unified model registry and routing

The local gateway presents one OpenAI-compatible endpoint. Clients select a
stable model identifier in the request body and do not know whether the model
runs on Windows Ollama, a manually started Runpod Pod, or Runpod Serverless.

## Stable model IDs

| Model ID | Policy |
| --- | --- |
| `qwen3.5:9b` | Windows Ollama only |
| `muse-glimmer-30b` | Manually started Pod preferred; Serverless fallback |

`GET /v1/models` advertises both identifiers. Unknown identifiers return an
OpenAI-style `model_not_found` error. Requests without a model identifier are
rejected so benchmark results cannot silently use a different model.

Example:

```json
{
  "model": "muse-glimmer-30b",
  "messages": [{"role": "user", "content": "Hello"}]
}
```

The optional `X-Muse-Backend` header can select `pod`, `serverless`, or
`ollama` only when compatible with the registry policy. It is intended for
diagnostics and controlled benchmark comparisons, not for infrastructure
discovery.

## Provenance

Successful responses include:

- `X-Muse-Model`
- `X-Muse-Backend`
- `X-Muse-Request-Id`
- `X-Muse-Fallback: true` when Muse fell back from Pod to Serverless

Gateway logs are structured and record model, selected backend, fallback,
status, request ID, and latency. They do not record prompts, tool arguments,
images, credentials, Pod addresses, or SSH details.

## Private Ollama route

The gateway reaches Windows Ollama over the Tailscale address. Ollama must be
bound to a network interface rather than its default localhost-only listener.
Windows Firewall must allow TCP 11434 only from the Linux gateway's Tailscale
address. Do not expose port 11434 to the public Internet or unrestricted LAN.

The gateway's public-facing surface remains the Linux Traefik route
`glimmer.local`, protected by the existing LAN-only middleware and the
gateway bearer token when configured.

## Benchmark boundary

Benchmark code knows only the gateway URL and the stable model ID. It must not
contain Pod IDs, endpoint IDs, GPU types, regions, volume paths, Ollama host
addresses, SSH keys, or fallback logic.
