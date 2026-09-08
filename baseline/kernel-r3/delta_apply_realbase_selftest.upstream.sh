#!/bin/sh
# Non-tautological replacement for delta_context_selftest.py.
#
# That script builds a synthetic gadget.c FROM THE DELTA'S OWN OLD-SIDE LINES
# and then applies the delta to it.  For any internally self-consistent patch
# that cannot fail, whatever the real base looks like -- and it passed while the
# real chain failed on two independent defects.
#
# This applies the delta to the actual post-image of the base chain, which is
# the only thing that can answer "does this delta apply to the 0001 shipped
# beside it".
#
#   ./delta_apply_realbase_selftest.sh /path/to/linux BASE_DIR DELTA
set -u
TREE="${1:?usage: $0 TREE BASE_DIR DELTA}"
BASE="${2:?}"
DELTA="${3:?}"
PIN=f5a7e2ae5f0a9a5caf59501457938eeb249a7dc8

git -C "$TREE" cat-file -e "$PIN^{commit}" 2>/dev/null || {
	echo "FAIL: $TREE does not contain the pin"; exit 1; }

D=$(mktemp -d); WT="$D/linux"
cleanup() { git -C "$TREE" worktree remove --force "$WT" >/dev/null 2>&1; rm -rf "$D"; }
trap cleanup EXIT HUP INT TERM

git -C "$TREE" worktree add --detach "$WT" "$PIN" >/dev/null 2>&1 || {
	echo "FAIL: cannot create worktree"; exit 1; }

rc=0
for p in "$BASE/0001-dwc2-r1-observer-v6.2.patch" \
         "$BASE/v62-llseek-fixup-v2.patch" \
         "$BASE/0001-dwc2-r1-observer-v6.3.1.patch"; do
	printf '  base  %-52s ' "$(basename "$p")"
	if git -C "$WT" apply "$p" 2>/tmp/rb.$$; then
		echo ok
	else
		echo "FAIL: $(head -1 /tmp/rb.$$)"; rc=1
	fi
done
rm -f /tmp/rb.$$
[ "$rc" -eq 0 ] || { echo; echo "DELTA REALBASE SELFTEST: FAIL (base chain broken)"; exit 1; }

printf '  delta %-52s ' "$(basename "$DELTA")"
if git -C "$WT" apply --check "$DELTA" 2>/tmp/rd.$$; then
	git -C "$WT" apply "$DELTA" && echo ok
else
	echo "FAIL: $(head -1 /tmp/rd.$$)"; rm -f /tmp/rd.$$
	echo; echo "DELTA REALBASE SELFTEST: FAIL"
	echo "  the delta does not apply to the base chain shipped beside it"
	exit 1
fi
rm -f /tmp/rd.$$

printf '  %-58s ' 'git diff --check'
git -C "$WT" diff --check && echo ok || { echo FAIL; exit 1; }

printf '  %-58s ' 'postimage declares semantic version 9'
grep -q 'DWC2_R1_DUMP_VERSION[[:space:]]*9U' "$WT/drivers/usb/dwc2/gadget.c" \
	&& echo ok || { echo FAIL; exit 1; }

printf '  %-58s ' 'stop_enter runs before each note_candidate'
if grep -q 'u8 cause = dwc2_r1_stop_enter(hsotg, DWC2_R1_STOP_DISABLE);' \
        "$WT/drivers/usb/dwc2/gadget.c" &&
   grep -q 'u8 cause = dwc2_r1_stop_enter(hs, DWC2_R1_STOP_DEQUEUE);' \
        "$WT/drivers/usb/dwc2/gadget.c"; then
	echo ok
else
	echo FAIL; exit 1
fi

printf '  %-58s ' 'candidates take the class as a parameter'
grep -q 'u32 ctrl, u8 cause' "$WT/drivers/usb/dwc2/gadget.c" \
	&& echo ok || { echo FAIL; exit 1; }

echo
echo "DELTA REALBASE SELFTEST: PASS"
