# Third-party notices

This repository builds and runs third-party software and downloads model
artifacts at worker startup. Their terms remain applicable.

| Component | Source | Notes |
| --- | --- | --- |
| llama.cpp | [ggml-org/llama.cpp](https://github.com/ggml-org/llama.cpp) | Cloned at the pinned `b10375` ref during the image build; see its MIT license. |
| CUDA base image | [NVIDIA CUDA images](https://hub.docker.com/r/nvidia/cuda) | `nvidia/cuda:12.8.1-devel-ubuntu22.04`; see NVIDIA and base-image notices. |
| Muse Glimmer GGUF artifacts | [Meta model repository](https://huggingface.co/meta-models/Muse-Glimmer-30B-GGUF) | Downloaded at runtime; follow Meta/Hugging Face model terms. |
| Python dependencies | PyPI projects listed in `Dockerfile` | Each dependency retains its own license. |

Do not treat the repository Apache-2.0 license as a license to redistribute
any third-party component or model artifact.
