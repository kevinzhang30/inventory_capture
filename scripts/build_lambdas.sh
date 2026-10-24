#!/usr/bin/env bash
# Builds dist/lambda/<package>.zip for the Python 3.12 arm64 Lambda runtime (docs/CONTRACTS.md §12).
# Cross-platform: dependencies come from manylinux aarch64 wheels, so this works on macOS and Linux.
#   scripts/build_lambdas.sh              # all packages
#   scripts/build_lambdas.sh ingest ops   # selected packages
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)
OUT="$ROOT/dist/lambda"
WORK="$ROOT/build/lambda"
if [ -n "${PYTHON:-}" ]; then PY="$PYTHON"
elif [ -x .venv/bin/python ]; then PY=.venv/bin/python
else PY=$(command -v python3)
fi
ALL=(ingest core_api extract cache_updater indexer reorder_checker review_dispatcher eval_nightly ops)
PACKAGES=("${@:-${ALL[@]}}")

rm -rf "$WORK/wheelhouse"
mkdir -p "$OUT" "$WORK/wheelhouse"

# 1) Wheels for our own packages (pure Python).
"$PY" -m pip wheel -q --no-deps -w "$WORK/wheelhouse" libs/common services/indexer
for pkg in "${PACKAGES[@]}"; do
  [ -d "services/$pkg" ] || { echo "unknown package: $pkg" >&2; exit 1; }
  "$PY" -m pip wheel -q --no-deps -w "$WORK/wheelhouse" "services/$pkg"
done

for pkg in "${PACKAGES[@]}"; do
  dist_name="inventory-${pkg//_/-}"
  target="$WORK/$pkg"
  rm -rf "$target"
  mkdir -p "$target"
  echo "==> $pkg ($dist_name)"
  # 2) Resolve everything as arm64 manylinux wheels for CPython 3.12.
  "$PY" -m pip install -q \
    --platform manylinux2014_aarch64 --platform manylinux_2_28_aarch64 \
    --implementation cp --python-version 3.12 --only-binary=:all: \
    --find-links "$WORK/wheelhouse" --target "$target" --upgrade \
    "$dist_name"
  # 3) ops also ships the Alembic migrations and seed data.
  if [ "$pkg" = "ops" ]; then
    mkdir -p "$target/db"
    cp db/alembic.ini "$target/db/"
    cp -R db/migrations db/seed "$target/db/"
  fi
  # 4) Trim bloat that is never imported at runtime.
  find "$target" -type d \( -name "__pycache__" -o -name "tests" -o -name "test" \) -prune -exec rm -rf {} +
  find "$target" -name "*.pyi" -delete
  rm -rf "${target:?}/bin"
  # boto3/botocore/s3transfer ship with the python3.12 Lambda runtime; dropping them keeps zips well under
  # the 50 MB direct-upload limit. Set KEEP_BOTO=1 to pin our own versions instead.
  if [ "${KEEP_BOTO:-0}" != "1" ]; then
    rm -rf "$target"/boto3 "$target"/boto3-* "$target"/botocore "$target"/botocore-* \
           "$target"/s3transfer "$target"/s3transfer-*
  fi
  # 5) Deterministic zip: sorted entries, fixed timestamps → stable source_code_hash.
  "$PY" - "$target" "$OUT/$pkg.zip" <<'PYZIP'
import os, sys, zipfile
src, dest = sys.argv[1], sys.argv[2]
entries = []
for root, dirs, files in os.walk(src):
    dirs.sort()
    for f in sorted(files):
        full = os.path.join(root, f)
        entries.append((os.path.relpath(full, src), full))
tmp = dest + ".tmp"
with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for rel, full in sorted(entries):
        info = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0))
        info.external_attr = (0o755 if os.access(full, os.X_OK) else 0o644) << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        with open(full, "rb") as fh:
            z.writestr(info, fh.read())
os.replace(tmp, dest)
PYZIP
  printf "    %s  %s\n" "$(du -h "$OUT/$pkg.zip" | cut -f1)" "$OUT/$pkg.zip"
done
