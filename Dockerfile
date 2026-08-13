FROM nvidia/cuda:12.8.1-devel-ubuntu22.04 AS llama-builder

ARG DEBIAN_FRONTEND=noninteractive
ARG LLAMA_CPP_REF=b10375
ARG CUDA_ARCHITECTURES=80;86;89;90;100;120
ARG BUILD_JOBS=4

ENV DEBIAN_FRONTEND=${DEBIAN_FRONTEND}

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cmake \
        curl \
        git \
        libcurl4-openssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt
RUN git clone --depth 1 --branch "${LLAMA_CPP_REF}" https://github.com/ggml-org/llama.cpp.git llama.cpp \
    && cmake -S /opt/llama.cpp -B /opt/llama.cpp/build \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_CUDA_ARCHITECTURES="${CUDA_ARCHITECTURES}" \
        -DGGML_CUDA=ON \
        -DLLAMA_CURL=ON \
        -DBUILD_SHARED_LIBS=OFF \
    && cmake --build /opt/llama.cpp/build --config Release --parallel "${BUILD_JOBS}" --target llama-server \
    && test -x /opt/llama.cpp/build/bin/llama-server

FROM nvidia/cuda:12.8.1-runtime-ubuntu22.04

ARG DEBIAN_FRONTEND=noninteractive

ENV DEBIAN_FRONTEND=${DEBIAN_FRONTEND} \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/runpod-volume/.cache/huggingface \
    HF_HUB_CACHE=/runpod-volume/.cache/huggingface/hub \
    MODEL_REPO=meta-models/Muse-Glimmer-30B-GGUF \
    MODEL_DIR=/runpod-volume/models/muse-glimmer-30b \
    PORT=8000

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        ca-certificates \
        libcurl4 \
        openssh-server \
        python3 \
        python3-pip \
        util-linux \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --no-cache-dir \
        huggingface_hub \
        "fastapi>=0.115,<1" \
        "httpx>=0.28,<1" \
        "uvicorn[standard]>=0.34,<1"

COPY --from=llama-builder /opt/llama.cpp/build/bin/llama-server /opt/llama-server
COPY start.sh /usr/local/bin/muse-glimmer-start
COPY proxy.py /opt/muse-glimmer-proxy.py
RUN chmod 0755 /usr/local/bin/muse-glimmer-start \
    && test -x /opt/llama-server

EXPOSE 8000 22
ENTRYPOINT ["/usr/local/bin/muse-glimmer-start"]

