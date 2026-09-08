#!/bin/sh
# Verify v6.3.2 semantic ABI v9 + P4, package revision r2.
# Without TREE: integrity, ABI tooling, structural delta contract, P4 selftests.
# With TREE: authoritative real-base apply at the campaign pin, postimage
# property guard, ABI regeneration, and scope audit.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
TREE="${1:-}"
PIN=f5a7e2ae5f0a9a5caf59501457938eeb249a7dc8
fails=0; skips=0
say(){ printf '%s\n' "$*"; }
ok(){ printf '  ok    %s\n' "$*"; }
bad(){ printf '  FAIL  %s\n' "$*"; fails=$((fails+1)); }
skip(){ printf '  skip  %s\n' "$*"; skips=$((skips+1)); }

say '=== 1. artifact integrity ==='
if (cd "$HERE" && sha256sum -c SHA256SUMS >/tmp/r2sum.$$ 2>&1); then
  ok "SHA256SUMS: $(grep -c ': OK' /tmp/r2sum.$$) files match"
else
  bad 'SHA256SUMS mismatch'; grep -v ': OK' /tmp/r2sum.$$ | sed 's/^/        /'
fi
rm -f /tmp/r2sum.$$

say ''; say '=== 2. ABI positive + negative gates ==='
if python3 "$HERE/abi_check.py" >/tmp/r2abi.$$ 2>&1; then ok "$(tail -1 /tmp/r2abi.$$)"; else bad 'ABI positive gate'; tail -40 /tmp/r2abi.$$ | sed 's/^/        /'; fi
rm -f /tmp/r2abi.$$
if "$HERE/abi_negative_selftest.sh" >/tmp/r2abin.$$ 2>&1; then
  grep -q 'exit status: 1' /tmp/r2abin.$$ && ok 'ABI negative control rejects injected hole with RC=1' || bad 'ABI negative control RC not 1'
else
  bad 'ABI negative selftest failed'; tail -30 /tmp/r2abin.$$ | sed 's/^/        /'
fi
rm -f /tmp/r2abin.$$

say ''; say '=== 3. portability ==='
if "$HERE/portability_selftest.sh" >/tmp/r2port.$$ 2>&1; then ok 'ABI tooling portable from scratch dir'; else bad 'portability selftest'; tail -30 /tmp/r2port.$$ | sed 's/^/        /'; fi
rm -f /tmp/r2port.$$

say ''; say '=== 4. semantic v9 structural contract ==='
if git apply --stat "$HERE/0003-v6.3.1-to-v6.3.2-denominator-causality.patch" >/tmp/r2stat.$$ 2>&1; then ok 'delta parses as unified diff'; else bad 'delta patch parser'; cat /tmp/r2stat.$$; fi
rm -f /tmp/r2stat.$$
if python3 "$HERE/delta_property_guard.py" --patch "$HERE/0003-v6.3.1-to-v6.3.2-denominator-causality.patch" >/tmp/r2prop.$$ 2>&1; then
  ok "$(tail -1 /tmp/r2prop.$$)"
else
  bad 'patch-local structural property contract'; cat /tmp/r2prop.$$ | sed 's/^/        /'
fi
rm -f /tmp/r2prop.$$
if command -v cc >/dev/null 2>&1; then
  D=$(mktemp -d)
  if cc -O2 -Wall -Wextra -Werror -o "$D/denominator_order_test" "$HERE/denominator_order_test.c" >/tmp/r2cc.$$ 2>&1 && "$D/denominator_order_test" >/tmp/r2den.$$ 2>&1; then
    grep -q 'DENOMINATOR ORDER TEST: PASS' /tmp/r2den.$$ && ok 'denominator defect reproducer/control PASS' || bad 'denominator test output unexpected'
  else
    bad 'denominator defect reproducer/control'; { cat /tmp/r2cc.$$; cat /tmp/r2den.$$ 2>/dev/null || true; } | tail -40 | sed 's/^/        /'
  fi
  rm -rf "$D" /tmp/r2cc.$$ /tmp/r2den.$$
else
  skip 'cc unavailable; denominator C control not rerun'
fi

say ''; say '=== 5. P4 parser/gate selftests ==='
if python3 -m py_compile "$HERE/dwc2_r1_v9.py" "$HERE/analyze_dwc2_r1_v9.py" "$HERE/r1_gate_v9.py" "$HERE/p4_selftest.py"; then ok 'Python compile'; else bad 'Python compile'; fi
if python3 "$HERE/p4_selftest.py" >/tmp/r2p4.$$ 2>&1; then
  grep -q 'P4 SELFTEST: 26/26 PASS' /tmp/r2p4.$$ && ok 'P4 selftest 26/26' || bad 'P4 selftest count unexpected'
else
  bad 'P4 selftest failed'; tail -50 /tmp/r2p4.$$ | sed 's/^/        /'
fi
rm -f /tmp/r2p4.$$

say ''; say '=== 6. packaged evidence (not a substitute for local re-derivation) ==='
for f in evidence/v632-structural/build-v632-arm-y.log evidence/v632-structural/build-v632-arm-n.log evidence/v632-structural/scope-audit-v632.txt evidence/v632-structural/abi-check-v632.txt evidence/v632-structural/denominator-order-test.txt; do
  [ -s "$HERE/$f" ] && ok "$f present" || bad "$f missing/empty"
done
say '      note: these are supplied build/audit artifacts; TREE mode below is authoritative for applicability/ABI/scope.'

say ''; say '=== 7. tree-dependent real-base apply/ABI/scope ==='
if [ -z "$TREE" ]; then
  skip 'no Linux tree supplied; real-base applicability is not re-derived here'
else
  if ! git -C "$TREE" cat-file -e "$PIN^{commit}" 2>/dev/null; then
    bad 'supplied tree does not contain campaign pin'
  else
    D=$(mktemp -d); WT="$D/linux"
    cleanup(){ git -C "$TREE" worktree remove --force "$WT" >/dev/null 2>&1 || true; rm -rf "$D"; }
    trap cleanup EXIT HUP INT TERM
    if git -C "$TREE" worktree add --detach "$WT" "$PIN" >/tmp/r2wt.$$ 2>&1; then
      ok 'temporary worktree created at pin'
      if git -C "$WT" apply "$HERE/base/0001-dwc2-r1-observer-v6.2.patch" && \
         git -C "$WT" apply "$HERE/base/v62-llseek-fixup-v2.patch" && \
         git -C "$WT" apply "$HERE/0001-dwc2-r1-observer-v6.3.1.patch" && \
         git -C "$WT" apply "$HERE/0003-v6.3.1-to-v6.3.2-denominator-causality.patch"; then
        ok 'pin -> v6.2 -> correct fixup -> v6.3.1 -> structural v6.3.2 applies'
        git -C "$WT" diff --check >/tmp/r2diff.$$ 2>&1 && ok 'git diff --check' || { bad 'git diff --check'; cat /tmp/r2diff.$$; }
        rm -f /tmp/r2diff.$$
        if python3 "$HERE/delta_property_guard.py" --gadget "$WT/drivers/usb/dwc2/gadget.c" >/tmp/r2post.$$ 2>&1; then ok "$(tail -1 /tmp/r2post.$$)"; else bad 'postimage structural property guard'; cat /tmp/r2post.$$ | sed 's/^/        /'; fi
        rm -f /tmp/r2post.$$
        if python3 "$HERE/abi_check.py" --gadget "$WT/drivers/usb/dwc2/gadget.c" >/tmp/r2live.$$ 2>&1; then ok 'ABI regenerated from real v6.3.2 postimage'; else bad 'postimage ABI'; tail -40 /tmp/r2live.$$ | sed 's/^/        /'; fi
        rm -f /tmp/r2live.$$
        if python3 "$HERE/scope_audit_v62.py" "$WT/drivers/usb/dwc2/gadget.c" >/tmp/r2scope.$$ 2>&1; then ok "scope audit: $(tail -1 /tmp/r2scope.$$)"; else bad 'scope audit'; tail -30 /tmp/r2scope.$$ | sed 's/^/        /'; fi
        rm -f /tmp/r2scope.$$
      else
        bad 'patch chain failed on exact pin'
      fi
      cleanup; trap - EXIT HUP INT TERM
    else
      bad 'could not create temporary worktree'; cat /tmp/r2wt.$$ | sed 's/^/        /'
    fi
    rm -f /tmp/r2wt.$$
  fi
fi

say ''
if [ "$fails" -gt 0 ]; then say "VERIFY_P4_R2: $fails FAILURE(S), $skips skipped"; exit 1; fi
say "VERIFY_P4_R2: all checks passed ($skips skipped)"
