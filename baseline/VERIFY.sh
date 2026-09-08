#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$HERE"
TREE=${1-}
fail=0
run() {
  name=$1; shift
  printf '\n=== %s ===\n' "$name"
  if "$@"; then
    printf -- '-- %s: PASS\n' "$name"
  else
    printf -- '-- %s: FAIL\n' "$name" >&2
    fail=1
  fi
}
run integrity sha256sum -c SHA256SUMS
run duplicates python3 check_duplicates.py
run contract python3 check_contract.py
run contract-selftest python3 contract_selftest.py
run epoch-contract sh -c 'cd pipeline && python3 freeze_epoch.py --epoch-id VERIFY --check-only >/dev/null'
run host sh -c 'cd host && ./VERIFY.sh'
run epoch-host python3 epoch_host_integration_selftest.py
run pipeline sh -c 'cd pipeline && ./VERIFY.sh'
if [ -n "$TREE" ]; then
  run kernel sh -c 'cd kernel-r3 && ./VERIFY.sh "$1"' sh "$TREE"
else
  run kernel-local sh -c 'cd kernel-r3 && ./VERIFY.sh'
fi
if [ "$fail" -ne 0 ]; then
  echo 'R1A_V4_2_VERIFY: FAIL' >&2
  exit 1
fi
echo 'R1A_V4_2_VERIFY: PASS (runtime not executed)'
