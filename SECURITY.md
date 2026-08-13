# Security policy

## Scope

The worker exposes an OpenAI-compatible HTTP API and can emit tool calls. It
does not execute tools, provide tenant authentication, or replace an
application policy layer. Deploy it behind Runpod authentication and an
application-level authorization, rate-limit, and audit layer.

## Reporting a vulnerability

Please do not open a public issue for a security vulnerability. Use GitHub's
private vulnerability reporting or a private security advisory for this
repository and include:

- affected commit or image digest;
- a minimal reproduction that does not contain secrets or user data;
- impact and required configuration;
- a suggested mitigation, if known.

If private reporting is unavailable, contact the repository owner through a
private GitHub channel and do not disclose credentials in the report.

## Secret handling

Never commit Runpod API keys, GitHub tokens, registry passwords, Hugging Face
tokens, network-volume contents, model files, or unredacted request logs.
