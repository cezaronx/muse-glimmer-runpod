[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Registry,
    [string]$Repository,
    [string]$Tag = "b10375",
    [string]$LlamaCppRef = "b10375",
    [string]$CudaArchitectures = "86;89;90",
    [switch]$NoCache
)

$ErrorActionPreference = "Stop"
$bundle = (Resolve-Path -LiteralPath $PSScriptRoot).Path

if ([string]::IsNullOrWhiteSpace($Repository)) {
    $Repository = if ($env:IMAGE_REPOSITORY) { $env:IMAGE_REPOSITORY } else { "ai-security-lab/muse-glimmer-runpod" }
}
$image = "{0}/{1}:{2}" -f $Registry.TrimEnd('/'), $Repository.TrimStart('/'), $Tag

Write-Warning "This command builds and publishes $image."
Write-Warning "Run 'docker login $Registry' separately before continuing."
$confirmation = Read-Host "Type PUBLISH $image to continue"
if ($confirmation -cne "PUBLISH $image") {
    throw "Publication cancelled. No image was pushed."
}

$dockerArgs = @(
    "buildx", "build",
    "--platform", "linux/amd64",
    "--file", (Join-Path $bundle "Dockerfile"),
    "--build-arg", "LLAMA_CPP_REF=$LlamaCppRef",
    "--build-arg", "CUDA_ARCHITECTURES=$CudaArchitectures",
    "--tag", $image,
    "--push"
)
if ($NoCache) { $dockerArgs += "--no-cache" }
$dockerArgs += $bundle

& docker @dockerArgs
if ($LASTEXITCODE -ne 0) {
    throw "Docker publication failed with exit code $LASTEXITCODE"
}

Write-Host "Published: $image"
Write-Host "Record the registry digest printed by Docker and deploy that digest to Runpod."
