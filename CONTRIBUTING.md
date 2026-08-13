# Contributing

Issues and pull requests that improve reproducibility, compatibility, and
security are welcome.

## Before opening a pull request

1. Run `python validate_worker.py` when Python is available.
2. Keep model downloads and inference out of static validation.
3. Do not add model weights, credentials, private volume IDs, or user data.
4. Update `README.md`, `THIRD_PARTY_NOTICES.md`, or `CHANGELOG.md` when the
   deployment contract changes.
5. Explain changes to the pinned llama.cpp ref, artifact filenames, CUDA
   targets, startup flags, or tool-call behavior.

## Image changes

Image publication is intentionally a manual GitHub Actions workflow. Use an
immutable tag or digest for deployment and verify the resulting image on a
CUDA-capable Runpod worker before changing production settings.
