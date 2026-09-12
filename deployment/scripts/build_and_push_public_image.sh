#!/usr/bin/env bash
# Build the public-demo API image (with the curated dataset baked in) and push it to a
# registry render.yaml's finqa-api-public service pulls from. Run this LOCALLY, from the
# repo root -- it needs your own registry login (e.g. `docker login ghcr.io`), which is
# exactly the kind of external-account action that isn't done for you automatically.
#
# Usage:
#   deployment/scripts/build_and_push_public_image.sh ghcr.io/YOUR_GITHUB_USERNAME/finqa-api-public:latest
#
# For GHCR specifically, log in once with a GitHub personal access token that has
# `write:packages` scope:
#   echo "$GITHUB_TOKEN" | docker login ghcr.io -u YOUR_GITHUB_USERNAME --password-stdin
set -euo pipefail

IMAGE="${1:?usage: $0 <registry>/<repo>:<tag>, e.g. ghcr.io/you/finqa-api-public:latest}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "== 1/3  rebuilding the curated public dataset from database/data/finqa_v2.db =="
python deployment/scripts/build_public_dataset.py

echo "== 2/3  building $IMAGE =="
docker build -f deployment/docker/api.public.Dockerfile -t "$IMAGE" .

echo "== 3/3  pushing $IMAGE =="
docker push "$IMAGE"

echo "Done. Point render.yaml's finqa-api-public.image.url at: $IMAGE"
echo "Then in the Render dashboard: Manual Deploy -> Deploy latest commit (or it picks up"
echo "the new tag automatically if the service is set to track ':latest')."
