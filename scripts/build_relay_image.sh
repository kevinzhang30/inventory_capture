#!/usr/bin/env bash
# Builds the outbox-relay image for linux/arm64 and pushes it to ECR. Prints the image URI on the last line.
#   scripts/build_relay_image.sh <account>.dkr.ecr.<region>.amazonaws.com/invcap-dev-outbox-relay
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="${1:?usage: build_relay_image.sh <ecr-repository-url>}"
REGISTRY="${REPO%%/*}"
REGION=$(echo "$REGISTRY" | cut -d. -f4)
TAG="$(git rev-parse --short HEAD 2>/dev/null || date +%Y%m%d%H%M%S)-$(date +%s)"

aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY" >&2
docker buildx build --platform linux/arm64 -f services/outbox_relay/Dockerfile -t "$REPO:$TAG" --push . >&2
echo "$REPO:$TAG"
