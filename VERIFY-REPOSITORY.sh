#!/bin/sh
# Fail-closed repository integrity and campaign-readiness gate.
#
# This script intentionally fails while baseline/ is only a fragment.
# Baseline integrity and holder-producer readiness are reported independently:
# a canonical v4.2 baseline can remain intact while the next campaign is
# blocked because its device producer cannot satisfy the active holder merger.
set -u

# The repository gate must be read-only with respect to its own evidence tree.
# Python bytecode caches would change the archive Git-tree identity merely by
# running verification, so suppress them inside the gate rather than relying on
# the caller's environment.
PYTHONDONTWRITEBYTECODE=1
export PYTHONDONTWRITEBYTECODE

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$ROOT" || exit 2

fail=0
baseline_fail=0
holder_fail=0

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
        # Keep the failure auditable without flooding normal PASS output.
        sed 's/^/  /' "$tmp" >&2
    fi

    # Presence in a developer's working tree is not enough: every pinned path
    # must actually be carried by Git.  This prevents an ignored/untracked file
    # copied in by hand from making a dirty checkout look self-contained.
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
            # --no-index evaluates ignore policy even for an already tracked
            # file. A pinned artifact that policy would ignore after restore is
            # an unsatisfiable repository contract unless explicitly negated.
            if git check-ignore --no-index -q -- "$full" 2>/dev/null; then
                printf '  ignored pinned path: %s\n' "$full" >&2
                ignored_bad=1
            fi
        done < baseline/SHA256SUMS

        if [ "$tracked_bad" -eq 0 ]; then
            pass baseline_pins_tracked
        else
            failmsg baseline_pins_tracked
        fi
        if [ "$ignored_bad" -eq 0 ]; then
            pass baseline_pins_not_ignored
        else
            failmsg baseline_pins_not_ignored
        fi
    else
        # GitHub source archives intentionally omit .git.  Do not convert that
        # packaging fact into an integrity bypass: require an archive-native
        # proof bound to the exact tracked baseline subtree and ignore policy.
        archive_tmp=${TMPDIR:-/tmp}/dwc2-archive-tracking.$$
        if [ -f verify_archive_tracking.py ] &&            python3 verify_archive_tracking.py "$ROOT" >"$archive_tmp" 2>&1; then
            pass baseline_pins_tracked
            pass baseline_pins_not_ignored
            pass archive_tracking_proof
        else
            failmsg git_tracking_check_available
            [ -s "$archive_tmp" ] && sed 's/^/  /' "$archive_tmp" >&2
        fi
        rm -f "$archive_tmp"
    fi
fi

# 2. EPOCH_ARTIFACTS must come from the checked-in validator, not prose.
VALIDATOR=baseline/pipeline/r1a_manifest.py
FREEZER=baseline/pipeline/freeze_epoch.py

if [ -f "$VALIDATOR" ]; then
    pass epoch_validator_present
else
    failmsg epoch_validator_present
    printf '  missing: %s\n' "$VALIDATOR" >&2
fi

if [ -f "$FREEZER" ]; then
    pass epoch_freezer_present
else
    failmsg epoch_freezer_present
    printf '  missing: %s\n' "$FREEZER" >&2
fi

# Parse EPOCH_ARTIFACTS without importing the baseline code.  This prevents a
# broken or incomplete package from turning the checker itself into evidence.
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
    then
        pass epoch_keyset_parse
    else
        failmsg epoch_keyset_parse
    fi
else
    failmsg epoch_keyset_parse
fi

# The freezer's check-only mode is the executable resolver for the local epoch
# contract.  It must succeed only after all load-bearing local modules exist
# and the validator/freezer/gate agree on the keyset.
if [ -f "$VALIDATOR" ] && [ -f "$FREEZER" ]; then
    if python3 "$FREEZER" --epoch-id REPOSITORY-CHECK --check-only >/tmp/dwc2-epoch-check.$$ 2>&1; then
        pass epoch_local_resolution
    else
        failmsg epoch_local_resolution
        sed 's/^/  /' /tmp/dwc2-epoch-check.$$ >&2
    fi
    rm -f /tmp/dwc2-epoch-check.$$
else
    failmsg epoch_local_resolution
fi

# Snapshot baseline integrity before checking repository-external campaign
# sources.  A later producer failure must never be mislabeled as a damaged
# canonical archive requiring re-import.
baseline_fail=$fail

# 3. Canonical load-bearing harness source locations for the next campaign.
# These are repository-source completeness checks, not runtime binary hashes.
for spec in \
    'host_source:r1a-host/r1a_host.c' \
    'device_source:r1a-device/r1a_ffs_out_v2.c'
do
    label=${spec%%:*}
    path=${spec#*:}
    if [ -f "$path" ]; then
        pass "$label"
    else
        failmsg "$label"
        printf '  missing: %s\n' "$path" >&2
    fi
done

# Presence alone is not capability.  Because holder_merger is in the active
# keyset, the device source must expose the JSONL producer contract consumed by
# baseline/pipeline/holder_merge.py.  The checker also fails if the consumer
# contract drifts, so a stale hard-coded test cannot silently remain green.
holder_tmp=${TMPDIR:-/tmp}/dwc2-holder-contract.$$
if python3 verify_holder_contract.py >"$holder_tmp" 2>&1; then
    pass holder_producer_contract
else
    failmsg holder_producer_contract
    sed 's/^/  /' "$holder_tmp" >&2
    holder_fail=1
fi
rm -f "$holder_tmp"

# A checker nobody runs is a checker that can rot, and a discriminating control
# that is only listed in a document is not executable.  These are mandatory.
# holder_roundtrip.py builds the producer from source, so a C compiler is now a
# gate requirement; without one it reports "cannot run" and this fails.
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

if [ "$baseline_fail" -eq 0 ]; then
    printf '%s\n' 'REPOSITORY_BASELINE: PASS'
else
    printf '%s\n' 'REPOSITORY_BASELINE: INCOMPLETE / RE-IMPORT REQUIRED' >&2
fi

if [ "$holder_fail" -ne 0 ]; then
    printf '%s\n' 'HOLDER_CAMPAIGN_READINESS: BLOCKED / PRODUCER INCOMPATIBLE' >&2
fi

if [ "$fail" -ne 0 ]; then
    printf '%s\n' 'REPOSITORY_GATE: FAIL' >&2
    exit 1
fi

printf '%s\n' 'HOLDER_CAMPAIGN_READINESS: PASS'
printf '%s\n' 'REPOSITORY_GATE: PASS'
exit 0
