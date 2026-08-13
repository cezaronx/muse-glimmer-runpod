"""Static validation for the Runpod worker bundle.

This intentionally does not download model weights, build Docker, contact
Runpod, or start an inference server.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def require(text: str, fragment: str, path: Path) -> None:
    if fragment not in text:
        raise AssertionError(f"{path.name} is missing {fragment!r}")


def main() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    start = (ROOT / "start.sh").read_text(encoding="utf-8")
    proxy = (ROOT / "proxy.py").read_text(encoding="utf-8")
    build_script = (ROOT / "build-image.ps1").read_text(encoding="utf-8")
    publish_script = (ROOT / "publish-image.ps1").read_text(encoding="utf-8")

    require(dockerfile, "FROM nvidia/cuda:12.8.1-devel-ubuntu22.04 AS llama-builder", ROOT / "Dockerfile")
    require(dockerfile, "ARG LLAMA_CPP_REF=", ROOT / "Dockerfile")
    require(dockerfile, "ARG CUDA_ARCHITECTURES=", ROOT / "Dockerfile")
    require(dockerfile, "ARG BUILD_JOBS=", ROOT / "Dockerfile")
    require(dockerfile, "CMAKE_CUDA_ARCHITECTURES", ROOT / "Dockerfile")
    require(dockerfile, "-DGGML_CUDA=ON", ROOT / "Dockerfile")
    require(dockerfile, "--target llama-server", ROOT / "Dockerfile")
    require(dockerfile, "FROM nvidia/cuda:12.8.1-runtime-ubuntu22.04", ROOT / "Dockerfile")
    require(dockerfile, "COPY --from=llama-builder", ROOT / "Dockerfile")
    require(dockerfile, "COPY proxy.py", ROOT / "Dockerfile")
    require(dockerfile, "llama-server", ROOT / "Dockerfile")
    for fragment in (
        "Muse-Glimmer-30B-KQuant-Dynamic-Q4_K_XL.gguf",
        "mmproj-Muse-Glimmer-30B-Q4_K_M.gguf",
        "dflash-Muse-Glimmer-30B-Q4_K_M.gguf",
    ):
        require(start, fragment, ROOT / "start.sh")
    for fragment in (
        "--model-draft",
        "--spec-type",
        "--mmproj",
        "--jinja",
        "--reasoning-format",
        "--chat-template-kwargs",
        "--metrics",
        '"/ping"',
        "status_code=204",
        "llama-server exited with return code",
        "MODEL_LOAD_TIMEOUT_SECONDS",
        "did not become healthy within",
        "llama-server is not running",
        "llama-server is unavailable",
        "StreamingResponse",
        "draft-dflash",
    ):
        require(proxy, fragment, ROOT / "proxy.py")
    for fragment in ("--tag", "LLAMA_CPP_REF", "CUDA_ARCHITECTURES", "DOCKER_CONFIG", "This script never pushes"):
        require(build_script, fragment, ROOT / "build-image.ps1")
    for fragment in ("--platform", "linux/amd64", "--push", "PUBLISH", "docker login"):
        require(publish_script, fragment, ROOT / "publish-image.ps1")

    for name in ("chat.json", "tool-call.json"):
        payload = json.loads((ROOT / "test_payloads" / name).read_text(encoding="utf-8"))
        assert payload["model"] == "muse-glimmer-30b"
        assert payload["messages"]
    tool_payload = json.loads(
        (ROOT / "test_payloads" / "tool-call.json").read_text(encoding="utf-8")
    )
    assert tool_payload["tools"][0]["type"] == "function"
    assert tool_payload["tools"][0]["function"]["name"] == "get_weather"

    print("worker bundle static validation: PASS")


if __name__ == "__main__":
    main()

