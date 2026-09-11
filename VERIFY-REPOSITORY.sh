#!/bin/sh
# Fail-closed repository integrity and campaign-readiness gate.
set -u

# Running verification must not mutate the evidence tree via Python caches.
PYTHONDONTWRITEBYTECODE=1
export PYTHONDONTWRITEBYTECODE

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT" || exit 2

fail=0
baseline_fail=0
holder_fail=0
foundation_fail=0

pass() { printf '%-34s %s\n' "$1" PASS; }
failmsg() { printf '%-34s %s\n' "$1" FAIL >&2; fail=1; }

printf '%s\n' '=== DWC2 repository completeness gate ==='

# 1. The baseline manifest is authoritative for the imported baseline bytes.
if [ ! -f baseline/SHA256SUMS ]; then
    failmsg baseline_manifest_present
else
    pass baseline_manifest_present

    tmp=${TMPDIR:-/tmp}/dwc2-baseline-sha.$$
    trap 'rm -f "$tmp"' EXIT HUP INT TERM
    if (cd baseline && sha256sum -c SHA256SUMS) >"$tmp" 2>&1; then
        pass baseline_sha256_complete
    else
        failmsg baseline_sha256_complete
        sed 's/^/  /' "$tmp" >&2
    fi

    if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        tracked_bad=0
        ignored_bad=0
        while read -r digest path; do
            [ -n "${digest:-}" ] || continue
            [ -n "${path:-}" ] || continue
            full="baseline/$path"
            if ! git ls-files --error-unmatch -- "$full" >/dev/null 2>&1; then
                printf '  untracked pinned path: %s\n' "$full" >&2
                tracked_bad=1
            fi
            if git check-ignore --no-index -q -- "$full" 2>/dev/null; then
                printf '  ignored pinned path: %s\n' "$full" >&2
                ignored_bad=1
            fi
        done < baseline/SHA256SUMS

        if [ "$tracked_bad" -eq 0 ]; then pass baseline_pins_tracked; else failmsg baseline_pins_tracked; fi
        if [ "$ignored_bad" -eq 0 ]; then pass baseline_pins_not_ignored; else failmsg baseline_pins_not_ignored; fi
    else
        archive_tmp=${TMPDIR:-/tmp}/dwc2-archive-tracking.$$
        if [ -f verify_archive_tracking.py ] && python3 verify_archive_tracking.py "$ROOT" >"$archive_tmp" 2>&1; then
            pass baseline_pins_tracked
            pass baseline_pins_not_ignored
        else
            failmsg git_tracking_check_available
            [ -s "$archive_tmp" ] && sed 's/^/  /' "$archive_tmp" >&2
        fi
        rm -f "$archive_tmp"
    fi

    # 1b. Archive-native provenance proof, run in BOTH modes.
    #
    # This previously ran only when git was absent. In a git checkout the gate
    # proved tracking with `git ls-files` and never evaluated the binding
    # between baseline/ and its authenticated source tree, so the gate could
    # report green while the proof a reviewer runs on a tarball was failing.
    # That is exactly what happened when a redaction rewrote pinned bytes:
    # every manifest was regenerated to agree with the new bytes, the gate
    # stayed green, and only the archive proof caught the broken binding.
    #
    # The constants it checks cannot be regenerated honestly. They tie the
    # tree to an authenticated import, so updating them to match edited bytes
    # would assert only that the tree is whatever it currently is.
    if [ -f verify_archive_tracking.py ]; then
        proof_tmp=${TMPDIR:-/tmp}/dwc2-archive-proof.$$
        if python3 verify_archive_tracking.py "$ROOT" >"$proof_tmp" 2>&1; then
            pass archive_tracking_proof
        else
            failmsg archive_tracking_proof
            sed 's/^/  /' "$proof_tmp" >&2
            baseline_fail=1
        fi
        rm -f "$proof_tmp"
    else
        failmsg archive_tracking_proof
        printf '  missing: verify_archive_tracking.py\n' >&2
        baseline_fail=1
    fi
fi

# 2. EPOCH_ARTIFACTS must come from the checked-in validator, not prose.
VALIDATOR=baseline/pipeline/r1a_manifest.py
FREEZER=baseline/pipeline/freeze_epoch.py

if [ -f "$VALIDATOR" ]; then pass epoch_validator_present; else failmsg epoch_validator_present; printf '  missing: %s\n' "$VALIDATOR" >&2; fi
if [ -f "$FREEZER" ]; then pass epoch_freezer_present; else failmsg epoch_freezer_present; printf '  missing: %s\n' "$FREEZER" >&2; fi

if [ -f "$VALIDATOR" ]; then
    if python3 - "$VALIDATOR" <<'PY'
import ast
import sys
from pathlib import Path
p = Path(sys.argv[1])
tree = ast.parse(p.read_text(), filename=str(p))
value = None
for node in tree.body:
    if isinstance(node, (ast.Assign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(t, ast.Name) and t.id == 'EPOCH_ARTIFACTS' for t in targets):
            value = ast.literal_eval(node.value)
            break
if not isinstance(value, (list, tuple)) or not value or not all(isinstance(x, str) and x for x in value):
    raise SystemExit('EPOCH_ARTIFACTS is missing or is not a non-empty literal string sequence')
if len(set(value)) != len(value):
    raise SystemExit('EPOCH_ARTIFACTS contains duplicate keys')
print('  EPOCH_ARTIFACTS:', ', '.join(value))
PY
    then pass epoch_keyset_parse; else failmsg epoch_keyset_parse; fi
else
    failmsg epoch_keyset_parse
fi

if [ -f "$VALIDATOR" ] && [ -f "$FREEZER" ]; then
    epoch_tmp=${TMPDIR:-/tmp}/dwc2-epoch-check.$$
    if python3 "$FREEZER" --epoch-id REPOSITORY-CHECK --check-only >"$epoch_tmp" 2>&1; then
        pass epoch_local_resolution
    else
        failmsg epoch_local_resolution
        sed 's/^/  /' "$epoch_tmp" >&2
    fi
    rm -f "$epoch_tmp"
else
    failmsg epoch_local_resolution
fi

baseline_fail=$fail

# 3. Canonical load-bearing harness source locations.
for spec in \
    'host_source:r1a-host/r1a_host.c' \
    'device_source:r1a-device/r1a_ffs_out_v2.c'
do
    label=${spec%%:*}
    path=${spec#*:}
    if [ -f "$path" ]; then pass "$label"; else failmsg "$label"; printf '  missing: %s\n' "$path" >&2; fi
done

# 4. Canonical POST-UNMAP source foundation. A clean main checkout must carry
# every definition/tool used by L2, G2.5, PRIMARY-A and PRIMARY-B.
for spec in \
    'foundation_g0:docs/POST-UNMAP-DMA-G0.md' \
    'foundation_l2:docs/POST-UNMAP-DMA-L2.md' \
    'foundation_g25:docs/POST-UNMAP-DMA-G2.5.md' \
    'foundation_object_gate:docs/POST-UNMAP-DMA-OBJECT-GATE.md' \
    'foundation_candidates:docs/POST-UNMAP-DMA-G2.5-CANDIDATES.md' \
    'foundation_dma_api_tool:tools/dma_api_debug_gate.py' \
    'foundation_object_tool:tools/capture_ep_dequeue_object_gate.py'
do
    label=${spec%%:*}
    path=${spec#*:}
    if [ -f "$path" ]; then
        pass "$label"
    else
        failmsg "$label"
        printf '  missing: %s\n' "$path" >&2
        foundation_fail=1
    fi
done

if python3 - <<'PY'
from pathlib import Path
requirements = {
    'docs/POST-UNMAP-DMA-L2.md': ['K_sw_ATTEMPTED', 'K_hw', 'PRIMARY-A', 'PRIMARY-B'],
    'docs/POST-UNMAP-DMA-G2.5.md': ['TARGET_BUILD_ID', 'PRIMARY-A', 'PRIMARY-B'],
    'docs/POST-UNMAP-DMA-OBJECT-GATE.md': ['PENDING_OBJECT_GATE', 'OBJECT-PROVEN', 'KILLED', '.debug_line', 'file:line'],
    'docs/POST-UNMAP-DMA-G0.md': ['DMA_API_DEBUG', 'tools/dma_api_debug_gate.py', 'boot_id', 'dwc2_bindings', 'driver_filter'],
    'docs/METHODOLOGY.md': ['positive predicate', 'negative control'],
}
for path, tokens in requirements.items():
    text = Path(path).read_text()
    for token in tokens:
        if token not in text:
            raise SystemExit(f'{path}: missing canonical token {token}')
PY
then
    pass source_foundation_semantics
else
    failmsg source_foundation_semantics
    foundation_fail=1
fi

if grep -Fq 'SUPERSEDED BY v4 — do not run' r1a-device/instrumentation/R1A-RESET-INSTRUMENTATION-v3.RECEIPT.txt; then
    pass v3_supersession_marked
else
    failmsg v3_supersession_marked
    foundation_fail=1
fi

if grep -Fq 'HISTORICAL SNAPSHOT — SUPERSEDED' docs/RESEARCH-GAPS-2026-09-08.md; then
    pass research_gap_snapshot_marked
else
    failmsg research_gap_snapshot_marked
    foundation_fail=1
fi

for branch_name in audit-trail canonical-v4.2-reimport holder-v2.3 holder-v2.3-staging post-unmap-dma-g0 restore-g0-g1
do
    if ! grep -Fq "\`$branch_name\`" docs/REPOSITORY-POLICY.md; then
        printf '  missing branch classification: %s\n' "$branch_name" >&2
        foundation_fail=1
        fail=1
    fi
done
if [ "$foundation_fail" -eq 0 ]; then
    pass branch_and_source_policy
else
    printf '%-34s %s\n' branch_and_source_policy FAIL >&2
fi

# 5. Source-foundation executable gates must prove their discriminating controls.
# Merely shipping a selftest function is insufficient: repository acceptance runs it.
for spec in \
    'object_gate_selftest:tools/capture_ep_dequeue_object_gate.py' \
    'dma_api_debug_selftest:tools/dma_api_debug_gate.py'
do
    label=${spec%%:*}
    script=${spec#*:}
    ctl_tmp=${TMPDIR:-/tmp}/dwc2-$label.$$
    if [ -f "$script" ] && python3 "$script" selftest >"$ctl_tmp" 2>&1; then
        pass "$label"
    else
        failmsg "$label"
        [ -s "$ctl_tmp" ] && sed 's/^/  /' "$ctl_tmp" >&2
        foundation_fail=1
    fi
    rm -f "$ctl_tmp"
done

# 6. Holder producer contract and discriminating controls.
holder_tmp=${TMPDIR:-/tmp}/dwc2-holder-contract.$$
if python3 verify_holder_contract.py >"$holder_tmp" 2>&1; then
    pass holder_producer_contract
else
    failmsg holder_producer_contract
    sed 's/^/  /' "$holder_tmp" >&2
    holder_fail=1
fi
rm -f "$holder_tmp"

for spec in \
    'holder_contract_selftest:verify_holder_contract_selftest.py' \
    'holder_log_guard_selftest:holder_log_guard_selftest.py' \
    'holder_roundtrip:holder_roundtrip.py'
do
    label=${spec%%:*}
    script=${spec#*:}
    if [ ! -f "$script" ]; then
        failmsg "$label"
        printf '  missing: %s\n' "$script" >&2
        holder_fail=1
        continue
    fi
    ctl_tmp=${TMPDIR:-/tmp}/dwc2-$label.$$
    if python3 "$script" >"$ctl_tmp" 2>&1; then
        pass "$label"
    else
        failmsg "$label"
        sed 's/^/  /' "$ctl_tmp" >&2
        holder_fail=1
    fi
    rm -f "$ctl_tmp"
done

# 7. Status-document drift guard.
#
# Freeze the verdict of the evidence checks (1-6) before the guard runs.  The
# documents describe the state of the evidence, so they must be measured
# against that verdict and not against one the guard itself perturbed: a defect
# in the guard would otherwise flip v_gate and report every truthful document
# as stale, burying the real cause under noise.
evidence_fail=$fail

# The selftest validates the sync checker against fixture trees.  It sets only
# the overall verdict: a broken drift guard is not a holder-producer
# incompatibility and must never be reported as one.
if [ ! -f verify_status_sync_selftest.py ]; then
    failmsg status_sync_selftest
    printf '  missing: verify_status_sync_selftest.py\n' >&2
else
    sst_tmp=${TMPDIR:-/tmp}/dwc2-status-sync-selftest.$$
    if python3 verify_status_sync_selftest.py >"$sst_tmp" 2>&1; then
        pass status_sync_selftest
    else
        failmsg status_sync_selftest
        sed 's/^/  /' "$sst_tmp" >&2
    fi
    rm -f "$sst_tmp"
fi

# 8. Status-document sync.
#
# Resolve the evidence verdict into the exact strings the documents are required
# to declare, then compare.  A stale declaration is a gate failure in either
# direction: a stale RED invites a reader to "repair" a closed blocker, which in
# this repository means editing authenticated bytes.
if [ "$baseline_fail" -eq 0 ]; then
    v_baseline='PASS'
else
    v_baseline='INCOMPLETE / RE-IMPORT REQUIRED'
fi

if [ "$foundation_fail" -eq 0 ]; then
    v_foundation='PASS'
else
    v_foundation='FAIL / MAIN NOT SELF-CONTAINED'
fi

if [ "$holder_fail" -eq 0 ]; then
    v_holder='PASS'
else
    v_holder='BLOCKED / PRODUCER INCOMPATIBLE'
fi

# Held to the evidence checks alone — excluding both the selftest above and the
# sync check below.  Including the sync check would be circular and could never
# fail; including the selftest would make a guard defect masquerade as document
# drift.  The gate's own exit status still reflects every check.
if [ "$evidence_fail" -eq 0 ]; then
    v_gate='PASS'
else
    v_gate='FAIL'
fi

if [ ! -f verify_status_sync.py ]; then
    failmsg status_sync
    printf '  missing: verify_status_sync.py\n' >&2
else
    sync_tmp=${TMPDIR:-/tmp}/dwc2-status-sync.$$
    if python3 verify_status_sync.py \
        "$v_baseline" "$v_foundation" "$v_holder" "$v_gate" >"$sync_tmp" 2>&1; then
        pass status_sync
    else
        failmsg status_sync
        sed 's/^/  /' "$sync_tmp" >&2
    fi
    rm -f "$sync_tmp"
fi

if [ "$baseline_fail" -eq 0 ]; then
    printf '%s\n' "REPOSITORY_BASELINE: $v_baseline"
else
    printf '%s\n' "REPOSITORY_BASELINE: $v_baseline" >&2
fi

if [ "$foundation_fail" -eq 0 ]; then
    printf '%s\n' "SOURCE_FOUNDATION: $v_foundation"
else
    printf '%s\n' "SOURCE_FOUNDATION: $v_foundation" >&2
fi

if [ "$holder_fail" -ne 0 ]; then
    printf '%s\n' "HOLDER_CAMPAIGN_READINESS: $v_holder" >&2
fi

if [ "$fail" -ne 0 ]; then
    printf '%s\n' 'REPOSITORY_GATE: FAIL' >&2
    exit 1
fi

printf '%s\n' "HOLDER_CAMPAIGN_READINESS: $v_holder"
printf '%s\n' 'REPOSITORY_GATE: PASS'
exit 0
