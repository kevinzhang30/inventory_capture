#!/usr/bin/env bash
# Creates .venv and installs every Python package editable, in dependency order.
#   scripts/dev_install.sh            # everything except the desktop app
#   WITH_DESKTOP=1 scripts/dev_install.sh
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-$(command -v python3.12 || command -v python3)}"
[ -d .venv ] || "$PY" -m venv .venv
PIP=".venv/bin/pip"
"$PIP" install -q --upgrade pip
PKGS=(
  libs/common libs/capture_client db
  services/ingest services/extract services/outbox_relay services/cache_updater services/indexer
  services/reorder_checker services/core_api services/review_dispatcher services/eval_nightly services/ops
  local/gateway eval loadtest/simulator
)
[ "${WITH_DESKTOP:-0}" = "1" ] && PKGS+=(apps/desktop)
ARGS=()
for p in "${PKGS[@]}"; do ARGS+=(-e "$p"); done
"$PIP" install -q "${ARGS[@]}"
"$PIP" install -q -r requirements-dev.txt
echo "installed ${#PKGS[@]} packages into .venv"
