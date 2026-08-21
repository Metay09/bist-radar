#!/usr/bin/env bash
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
docker build -f "$repo_dir/frontend/Dockerfile.playwright" -t bist-radar-playwright "$repo_dir/frontend"
docker run --rm -v "$repo_dir/frontend/artifacts:/workspace/artifacts" bist-radar-playwright
