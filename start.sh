#!/usr/bin/env bash
set -Eeuo pipefail

log() {
    printf '[muse-glimmer] %s\n' "$*"
}

die() {
    printf '[muse-glimmer] ERROR: %s\n' "$*" >&2
    exit 1
}

: "${MODEL_REPO:=meta-models/Muse-Glimmer-30B-GGUF}"
: "${MODEL_DIR:=/runpod-volume/models/muse-glimmer-30b}"
: "${MAIN_MODEL_FILE:=Muse-Glimmer-30B-KQuant-Dynamic-Q4_K_XL.gguf}"
: "${MMPROJ_FILE:=mmproj-Muse-Glimmer-30B-Q4_K_M.gguf}"
: "${DRAFT_MODEL_FILE:=dflash-Muse-Glimmer-30B-Q4_K_M.gguf}"
: "${PORT:=8000}"
: "${MODEL_ALIAS:=muse-glimmer-30b}"
: "${CONTEXT_SIZE:=131072}"
: "${PARALLEL_SLOTS:=1}"
: "${N_GPU_LAYERS:=all}"
: "${DRAFT_N_GPU_LAYERS:=all}"
: "${DRAFT_N_MAX:=3}"
: "${REASONING_BUDGET:=-1}"
: "${REASONING_STRENGTH:=high}"
: "${DOWNLOAD_MODELS:=1}"

[[ -x /opt/llama.cpp/build/bin/llama-server ]] || die "llama-server is missing from the image"

if [[ ! -d /runpod-volume && "${ALLOW_EPHEMERAL_MODEL_CACHE:-0}" != "1" ]]; then
    die "Runpod network volume is not mounted at /runpod-volume; set ALLOW_EPHEMERAL_MODEL_CACHE=1 only for disposable tests"
fi

mkdir -p "${MODEL_DIR}"

main_path="${MODEL_DIR}/${MAIN_MODEL_FILE}"
mmproj_path="${MODEL_DIR}/${MMPROJ_FILE}"
draft_path="${MODEL_DIR}/${DRAFT_MODEL_FILE}"
complete_marker="${MODEL_DIR}/.download-complete"

if [[ "${DOWNLOAD_MODELS}" == "1" ]]; then
    # flock makes the first-download path safe when more than one worker is
    # accidentally pointed at the same network volume.
    exec 9>"${MODEL_DIR}/.download.lock"
    flock 9

    if [[ ! -s "${main_path}" || ! -s "${mmproj_path}" || ! -s "${draft_path}" ]]; then
        log "Downloading official Muse Glimmer artifacts into ${MODEL_DIR}"
        rm -f "${complete_marker}"
        hf download "${MODEL_REPO}" \
            --local-dir "${MODEL_DIR}" \
            --include "${MAIN_MODEL_FILE}" \
            --include "${MMPROJ_FILE}" \
            --include "${DRAFT_MODEL_FILE}"
    fi

    [[ -s "${main_path}" ]] || die "main GGUF was not downloaded: ${main_path}"
    [[ -s "${mmproj_path}" ]] || die "mmproj GGUF was not downloaded: ${mmproj_path}"
    [[ -s "${draft_path}" ]] || die "DFlash GGUF was not downloaded: ${draft_path}"
    touch "${complete_marker}"
else
    log "DOWNLOAD_MODELS=0; using existing files only"
    [[ -s "${main_path}" && -s "${mmproj_path}" && -s "${draft_path}" ]] \
        || die "DOWNLOAD_MODELS=0 requires all three GGUF files in ${MODEL_DIR}"
fi

log "Starting llama.cpp server ${MODEL_ALIAS} on 0.0.0.0:${PORT}"
export LLAMA_SERVER_BIN=/opt/llama.cpp/build/bin/llama-server
export LLAMA_MODEL_PATH="${main_path}"
export LLAMA_MMPROJ_PATH="${mmproj_path}"
export LLAMA_DRAFT_PATH="${draft_path}"
export LLAMA_SERVER_PORT=8080
export LLAMA_MODEL_ALIAS="${MODEL_ALIAS}"
export LLAMA_CONTEXT_SIZE="${CONTEXT_SIZE}"
export LLAMA_PARALLEL_SLOTS="${PARALLEL_SLOTS}"
export LLAMA_N_GPU_LAYERS="${N_GPU_LAYERS}"
export LLAMA_DRAFT_N_GPU_LAYERS="${DRAFT_N_GPU_LAYERS}"
export LLAMA_DRAFT_N_MAX="${DRAFT_N_MAX}"
export LLAMA_REASONING_BUDGET="${REASONING_BUDGET}"
export LLAMA_REASONING_STRENGTH="${REASONING_STRENGTH}"
exec python3 /opt/muse-glimmer-proxy.py
