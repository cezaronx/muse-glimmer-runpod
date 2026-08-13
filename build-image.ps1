[CmdletBinding()]
param(
    [string]$Registry,
    [string]$Repository,
    [string]$Tag,
    [string]$LlamaCppRef = "b10375",
    [string]$CudaArchitectures = "86;89;90",
    [switch]$NoCache
)

$ErrorActionPreference = "Stop"
$bundle = (Resolve-Path -LiteralPath $PSScriptRoot).Path

if ([string]::IsNullOrWhiteSpace($Repository)) {
    $Repository = if ($env:IMAGE_REPOSITORY) { $env:IMAGE_REPOSITORY } else { "ai-security-lab/muse-glimmer-runpod" }
}
if ([string]::IsNullOrWhiteSpace($Tag)) {
    $Tag = if ($env:IMAGE_TAG) { $env:IMAGE_TAG } else { $LlamaCppRef }
}
if ([string]::IsNullOrWhiteSpace($Registry)) {
    $Registry = $env:CONTAINER_REGISTRY
}

$image = if ([string]::IsNullOrWhiteSpace($Registry)) {
    "${Repository}:${Tag}"
} else {
    "{0}/{1}:{2}" -f $Registry.TrimEnd('/'), $Repository.TrimStart('/'), $Tag
}

$dockerArgs = @(
    "build",
    "--file", (Join-Path $bundle "Dockerfile"),
    "--build-arg", "LLAMA_CPP_REF=$LlamaCppRef",
    "--build-arg", "CUDA_ARCHITECTURES=$CudaArchitectures",
    "--tag", $image
)
if ($NoCache) { $dockerArgs += "--no-cache" }
$dockerArgs += $bundle

Write-Host "Building local image: $image"
Write-Host "llama.cpp ref: $LlamaCppRef"
Write-Host "CUDA architectures: $CudaArchitectures"
$isolatedDockerConfig = Join-Path ([IO.Path]::GetTempPath()) "muse-glimmer-build-docker-config"
$previousDockerConfig = $env:DOCKER_CONFIG
New-Item -ItemType Directory -Force -Path $isolatedDockerConfig | Out-Null
try {
    # A local build must not read or alter the operator's registry credentials.
    $env:DOCKER_CONFIG = $isolatedDockerConfig
    & docker @dockerArgs
    $buildExitCode = $LASTEXITCODE
} finally {
    if ($null -eq $previousDockerConfig) {
        Remove-Item Env:DOCKER_CONFIG -ErrorAction SilentlyContinue
    } else {
        $env:DOCKER_CONFIG = $previousDockerConfig
    }
    Remove-Item -LiteralPath $isolatedDockerConfig -Recurse -Force -ErrorAction SilentlyContinue
}
if ($buildExitCode -ne 0) {
    throw "Docker build failed with exit code $buildExitCode"
}

Write-Host "Build complete: $image"
Write-Host "This script does not push or contact Runpod."
