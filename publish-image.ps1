[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Registry,
    [string]$Repository,
    [string]$Tag = "b10375",
    [string]$LlamaCppRef = "b10375",
    [string]$CudaArchitectures = "86;89;90",
    [ValidateRange(1, 32)]
    [int]$BuildJobs = 4,
    [switch]$NoCache,
    [switch]$Yes
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
    if ($Registry -match '://|\s') {
        throw "Registry must be a host name without a scheme or whitespace."
    }
    if ([string]::IsNullOrWhiteSpace($Repository) -or [string]::IsNullOrWhiteSpace($Tag)) {
        throw "Repository and tag cannot be empty."
    }
    return "{0}/{1}:{2}" -f $Registry.TrimEnd('/'), $Repository.TrimStart('/'), $Tag
}

Require-Command "docker"

if ([string]::IsNullOrWhiteSpace($Repository)) {
    $Repository = if ($env:IMAGE_REPOSITORY) { $env:IMAGE_REPOSITORY } else { "ai-security-lab/muse-glimmer-runpod" }
}
$image = Resolve-ImageReference -Registry $Registry -Repository $Repository -Tag $Tag

if (-not $Yes) {
    Write-Warning "This command builds and publishes $image."
    Write-Warning "Authenticate separately first: docker login $Registry"
    $confirmation = Read-Host "Type PUBLISH $image to continue"
    if ($confirmation -cne "PUBLISH $image") {
        throw "Publication cancelled. No image was pushed."
    }
}

$dockerArgs = @(
    "buildx", "build",
    "--progress=plain",
    "--platform", "linux/amd64",
    "--file", (Join-Path $bundle "Dockerfile"),
    "--build-arg", "LLAMA_CPP_REF=$LlamaCppRef",
    "--build-arg", "CUDA_ARCHITECTURES=$CudaArchitectures",
    "--build-arg", "BUILD_JOBS=$BuildJobs",
    "--tag", $image,
    "--push"
)
if ($NoCache) { $dockerArgs += "--no-cache" }
$dockerArgs += $bundle

Write-Host "Publishing image: $image"
Write-Host "llama.cpp ref: $LlamaCppRef"
Write-Host "CUDA architectures: $CudaArchitectures"
Write-Host "Compiler jobs: $BuildJobs"

& docker @dockerArgs
if ($LASTEXITCODE -ne 0) {
    throw "Docker publication failed with exit code $LASTEXITCODE."
}

Write-Host "Published: $image"
Write-Host "Verify and deploy the immutable digest, not a mutable tag:"
& docker buildx imagetools inspect $image
