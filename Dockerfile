ARG BASE_IMAGE=ghcr.io/cezaronx/muse-glimmer-runpod@sha256:d7eb969a08b8b6a329810e1a699dedb101191e9a94a47dc8927520b44e2b0a23

# Start from the last successfully published Muse Glimmer image. This keeps
# the already-built llama.cpp b10375 binary while allowing a fast runtime
# diagnosis/fix cycle instead of recompiling CUDA on every attempt.
FROM ${BASE_IMAGE}

ARG DEBIAN_FRONTEND=noninteractive

ENV DEBIAN_FRONTEND=${DEBIAN_FRONTEND}

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        libgcc-s1 \
        libgomp1 \
        libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

COPY start.sh /usr/local/bin/muse-glimmer-start
COPY proxy.py /opt/muse-glimmer-proxy.py
RUN chmod 0755 /usr/local/bin/muse-glimmer-start \
    && test -x /opt/llama-server \
    && test -f /opt/muse-glimmer-proxy.py

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/muse-glimmer-start"]
