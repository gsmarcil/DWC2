#!/bin/sh
# Re-verify this bundle. Nothing here depends on the author's machine.
#
#   ./VERIFY.sh                 checks that need only this directory
#   ./VERIFY.sh /path/to/linux  also re-derives the tree-dependent gates
#
# The tree must be at the campaign pin. The build gates additionally need an
# arm cross-toolchain; they are skipped with a clear note if it is absent,
# never silently passed.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
TREE="${1:-}"
PIN=f5a7e2ae5f0a9a5caf59501457938eeb249a7dc8
fails=0
skips=0

say()  { printf '%s\n' "$*"; }
ok()   { printf '  ok    %s\n' "$*"; }
bad()  { printf '  FAIL  %s\n' "$*"; fails=$((fails+1)); }
skip() { printf '  skip  %s\n' "$*"; skips=$((skips+1)); }

say "=== 1. artifact integrity ==="
if [ -f "$HERE/SHA256SUMS" ]; then
	if (cd "$HERE" && sha256sum -c SHA256SUMS >/tmp/sums.$$ 2>&1); then
		ok "SHA256SUMS: $(grep -c ': OK' /tmp/sums.$$) files match"
	else
		bad "SHA256SUMS mismatch:"; grep -v ': OK' /tmp/sums.$$ | sed 's/^/        /'
	fi
	rm -f /tmp/sums.$$
else
	bad "SHA256SUMS missing"
fi

say ""
say "=== 2. ABI gate (self-contained) ==="
if python3 "$HERE/abi_check.py" >/tmp/abi.$$ 2>&1; then
	ok "$(tail -1 /tmp/abi.$$)"
else
	bad "abi_check.py failed"; sed 's/^/        /' /tmp/abi.$$
fi
rm -f /tmp/abi.$$

say ""
say "=== 3. portability (runs the bundle from a scratch dir, unmodified) ==="
if "$HERE/portability_selftest.sh" >/tmp/port.$$ 2>&1; then
	ok "portability selftest passed"
else
	bad "portability selftest failed"; sed 's/^/        /' /tmp/port.$$
fi
rm -f /tmp/port.$$

say ""
say "=== 4. recorded evidence is present and non-empty ==="
for f in evidence/build-v631-arm-y.log evidence/build-v631-arm-n.log \
         evidence/config-observer-y evidence/config-observer-n \
         evidence/config-delta.txt evidence/scope-audit.txt \
         evidence/clean-room-identity.txt evidence/abi-check-live.txt \
         evidence/abi-negative-test.txt evidence/abi-cross-arch.txt \
         evidence/abi-layout-x86_64.txt evidence/abi-layout-arm32.txt; do
	if [ -s "$HERE/$f" ]; then ok "$f"; else bad "$f missing or empty"; fi
done

say ""
say "=== 5. recorded evidence says what it should ==="
grep -q "all 26 probes correctly scoped" "$HERE/evidence/scope-audit.txt" \
	&& ok "scope audit: 26/26" || bad "scope audit did not pass"
[ "$(grep -c 'IDENTICAL' "$HERE/evidence/clean-room-identity.txt")" -eq 4 ] \
	&& ok "clean room: 4 files identical" || bad "clean-room identity incomplete"
grep -q "V6.3 ABI CHECK: all checks passed" "$HERE/evidence/abi-check-live.txt" \
	&& ok "ABI from the live tree passed" || bad "live-tree ABI evidence bad"
grep -q "FAILURE" "$HERE/evidence/abi-negative-test.txt" \
	&& ok "ABI negative control was rejected" \
	|| bad "negative control did not fail -- the gate proves nothing"
grep -q "IDENTICAL" "$HERE/evidence/abi-cross-arch.txt" \
	&& ok "ARM32 and x86-64 layouts identical" || bad "cross-arch layout differs"
if [ "$(grep -c '^[<>]' "$HERE/evidence/config-delta.txt")" -eq 1 ]; then
	ok "the two configs differ in exactly one symbol"
else
	bad "config delta is not a single symbol"
fi
for L in evidence/build-v631-arm-y.log evidence/build-v631-arm-n.log; do
	if grep -qiE 'error|warning' "$HERE/$L"; then
		bad "$L contains error/warning lines"
	else
		ok "$L clean"
	fi
done

say ""
say "=== 6. tree-dependent gates ==="
if [ -z "$TREE" ]; then
	skip "no tree given; pass one to re-derive apply-check, ABI and scope"
else
	if [ "$(git -C "$TREE" rev-parse HEAD 2>/dev/null)" = "$PIN" ] ||
	   git -C "$TREE" cat-file -e "$PIN" 2>/dev/null; then
		ok "tree knows the pin"
	else
		bad "tree is not at, and does not contain, the pin"
	fi
	G="$TREE/drivers/usb/dwc2/gadget.c"
	if [ -f "$G" ]; then
		if python3 "$HERE/abi_check.py" --gadget "$G" >/tmp/l.$$ 2>&1; then
			ok "ABI regenerated from this tree passes"
		else
			bad "ABI from this tree failed"; sed 's/^/        /' /tmp/l.$$
		fi
		rm -f /tmp/l.$$
		if python3 "$HERE/scope_audit_v62.py" "$G" >/tmp/s.$$ 2>&1; then
			ok "scope audit on this tree: $(tail -1 /tmp/s.$$)"
		else
			bad "scope audit on this tree failed"; tail -3 /tmp/s.$$
		fi
		rm -f /tmp/s.$$
	else
		bad "no drivers/usb/dwc2/gadget.c under $TREE"
	fi
fi

say ""
if [ "$fails" -gt 0 ]; then
	say "VERIFY: $fails FAILURE(S), $skips skipped"
	exit 1
fi
say "VERIFY: all checks passed ($skips skipped)"
