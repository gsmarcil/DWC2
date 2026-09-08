#!/bin/sh
# Authoritative applicability test against the actual pinned tree.
set -eu
TREE="${1:?usage: $0 /path/to/linux}"
HERE=$(cd "$(dirname "$0")" && pwd)
PIN=f5a7e2ae5f0a9a5caf59501457938eeb249a7dc8

git -C "$TREE" cat-file -e "$PIN^{commit}" 2>/dev/null || {
  echo "FAIL: tree does not contain pin"; exit 1; }
D=$(mktemp -d); WT="$D/linux"
cleanup(){ git -C "$TREE" worktree remove --force "$WT" >/dev/null 2>&1 || true; rm -rf "$D"; }
trap cleanup EXIT HUP INT TERM
git -C "$TREE" worktree add --detach "$WT" "$PIN" >/dev/null 2>&1 || {
  echo "FAIL: cannot create worktree"; exit 1; }
for p in "$HERE/base/0001-dwc2-r1-observer-v6.2.patch" \
         "$HERE/base/v62-llseek-fixup-v2.patch" \
         "$HERE/0001-dwc2-r1-observer-v6.3.1.patch" \
         "$HERE/0003-v6.3.1-to-v6.3.2-denominator-causality.patch"; do
  printf '  apply %-52s ' "$(basename "$p")"
  git -C "$WT" apply "$p" && echo ok || { echo FAIL; exit 1; }
done
git -C "$WT" diff --check
python3 "$HERE/delta_property_guard.py" --gadget "$WT/drivers/usb/dwc2/gadget.c"
echo "DELTA REALBASE SELFTEST: PASS"
