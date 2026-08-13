#!/usr/bin/env python3
"""Send a small OpenAI-compatible probe to the Runpod load-balancer endpoint."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_ENDPOINT = "80ooydmc06vh70"
DEFAULT_MODEL = "muse-glimmer-30b"


def local_dotenv_key() -> str | None:
    dotenv = Path(__file__).with_name(".env")
    if not dotenv.is_file():
        return None
    for line in dotenv.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() not in {"RUNPOD_KEY", "RUNPOD_API_KEY"}:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        return value or None
    return None


def request_json(url: str, token: str, payload: dict | None = None) -> tuple[int, dict | str]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=headers, method="POST" if body else "GET")
    try:
        with urlopen(request, timeout=600) as response:
            raw = response.read().decode("utf-8")
            try:
                return response.status, json.loads(raw)
            except json.JSONDecodeError:
                return response.status, raw
    except HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        return error.code, raw
    except URLError as error:
        return 0, str(error.reason)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=os.environ.get("RUNPOD_ENDPOINT_ID", DEFAULT_ENDPOINT))
    parser.add_argument("--model", default=os.environ.get("RUNPOD_MODEL", DEFAULT_MODEL))
    parser.add_argument(
        "--prompt",
        default="Give me a simple spaghetti sauce recipe.",
    )
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--temperature", type=float, default=0.7)
    args = parser.parse_args()

    token = (
        os.environ.get("RUNPOD_API_KEY")
        or os.environ.get("RUNPOD_KEY")
        or local_dotenv_key()
        or getpass.getpass("Runpod API key (hidden): ")
    )
    if not token:
        print("A Runpod API key is required; it is never written to the repository.", file=sys.stderr)
        return 2

    base_url = f"https://{args.endpoint}.api.runpod.ai"
    for attempt in range(1, 4):
        status, result = request_json(f"{base_url}/ping", token)
        if status == 200:
            break
        print(f"health attempt {attempt}/3: HTTP {status}: {result}", file=sys.stderr)
        if attempt < 3:
            time.sleep(10)
    else:
        return 1

    payload = {
        "model": args.model,
        "messages": [{"role": "user", "content": args.prompt}],
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
    }
    status, result = request_json(f"{base_url}/v1/chat/completions", token, payload)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if status == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
