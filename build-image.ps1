[CmdletBinding()]
param(
    [string]$Registry,
    [string]$Repository,
    [string]$Tag,
    [string]$LlamaCppRef = "b10375",
    [string]$CudaArchitectures = "86;89;90",
    [ValidateRange(1, 32)]
    [int]$BuildJobs = 4,
    [switch]$NoCache
)

$ErrorActionPreference = "Stop"
$bundle = (Resolve-Path -LiteralPath $PSScriptRoot).Path

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command not found: $Name"
    }
}

function Resolve-ImageReference {
    param([string]$Registry, [string]$Repository, [string]$Tag)
    if ([string]::IsNullOrWhiteSpace($Repository)) {
        throw "Repository cannot be empty."
    }
    if ([string]::IsNullOrWhiteSpace($Tag)) {
        throw "Tag cannot be empty."
    }
    if ($Registry -and $Registry -match '://|\s') {
        throw "Registry must be a host name without a scheme or whitespace."
    }
    if ($Registry) {
        return "{0}/{1}:{2}" -f $Registry.TrimEnd('/'), $Repository.TrimStart('/'), $Tag
    }
    return "{0}:{1}" -f $Repository.TrimStart('/'), $Tag
}

Require-Command "docker"

if ([string]::IsNullOrWhiteSpace($Repository)) {
    $Repository = if ($env:IMAGE_REPOSITORY) { $env:IMAGE_REPOSITORY } else { "ai-security-lab/muse-glimmer-runpod" }
}
if ([string]::IsNullOrWhiteSpace($Tag)) {
    $Tag = if ($env:IMAGE_TAG) { $env:IMAGE_TAG } else { $LlamaCppRef }
}
if ([string]::IsNullOrWhiteSpace($Registry)) {
    $Registry = $env:CONTAINER_REGISTRY
}

$image = Resolve-ImageReference -Registry $Registry -Repository $Repository -Tag $Tag
$dockerArgs = @(
    "build",
    "--progress=plain",
    "--file", (Join-Path $bundle "Dockerfile"),
    "--build-arg", "LLAMA_CPP_REF=$LlamaCppRef",
    "--build-arg", "CUDA_ARCHITECTURES=$CudaArchitectures",
    "--build-arg", "BUILD_JOBS=$BuildJobs",
    "--tag", $image
)
if ($NoCache) { $dockerArgs += "--no-cache" }
$dockerArgs += $bundle

Write-Host "Building local image: $image"
Write-Host "llama.cpp ref: $LlamaCppRef"
Write-Host "CUDA architectures: $CudaArchitectures"
Write-Host "Compiler jobs: $BuildJobs"

# Keep a local build isolated from the operator's registry credentials.
$isolatedDockerConfig = Join-Path ([IO.Path]::GetTempPath()) "muse-glimmer-build-docker-config"
$previousDockerConfig = $env:DOCKER_CONFIG
New-Item -ItemType Directory -Force -Path $isolatedDockerConfig | Out-Null
try {
    $env:DOCKER_CONFIG = $isolatedDockerConfig
    & docker @dockerArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Docker build failed with exit code $LASTEXITCODE."
    }
} finally {
    if ($null -eq $previousDockerConfig) {
        Remove-Item Env:DOCKER_CONFIG -ErrorAction SilentlyContinue
    } else {
        $env:DOCKER_CONFIG = $previousDockerConfig
    }
    Remove-Item -LiteralPath $isolatedDockerConfig -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "Build complete: $image"
Write-Host "This script never pushes an image or changes Runpod resources."
