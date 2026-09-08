#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$HERE"

# Synchronize duplicated load-bearing files from canonical copies before any
# test or hash.  check_duplicates.py is the guard that prevents stale siblings.
cp pipeline/r1a_manifest.py host/r1a_manifest.py
cp pipeline/dwc2_r1_v9.py kernel-r3/dwc2_r1_v9.py
cp pipeline/r1_gate_v9.py kernel-r3/r1_gate_v9.py
python3 check_duplicates.py >/dev/null

# Never package verification/build/cache/VCS side effects.
( cd host && make clean >/dev/null 2>&1 || true )
find . -type d -name __pycache__ -prune -exec rm -rf {} +
find . -type f \( -name '*.pyc' -o -name 'r1a_host' \) -delete

# A hidden VCS directory is never evidence.  Refuse rather than silently pack
# one; the tar command also excludes it defensively.
if find . -type d -name .git -print -quit | grep -q .; then
  echo 'REFUSING TO PACK: .git directory present in staging tree' >&2
  exit 1
fi

# Regenerate component sums first, because top-level SHA256SUMS must describe
# the exact component manifests that will be shipped.
for d in host pipeline kernel-r3; do
  ( cd "$d"
    find . -type f ! -name SHA256SUMS -printf '%P\n' | LC_ALL=C sort | xargs sha256sum > SHA256SUMS
  )
done

# Exact top-level bytes that will be packed. Exclude the top-level sum file
# itself and all VCS/cache/build products.
find . \
  -path './.git' -prune -o \
  -type d -name __pycache__ -prune -o \
  -type f ! -path './SHA256SUMS' ! -name '*.pyc' ! -name 'r1a_host' -printf '%P\n' \
  | LC_ALL=C sort | xargs sha256sum > SHA256SUMS

name=$(basename "$HERE")
parent=$(dirname "$HERE")
out="$parent/$name.tar.gz"
TZ=UTC tar --sort=name --mtime='UTC 2026-09-08 00:00:00' \
  --owner=0 --group=0 --numeric-owner --exclude="$name/.git" \
  -C "$parent" -cf - "$name" | gzip -n > "$out"
echo "$out"
sha256sum "$out"
