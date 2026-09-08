#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$HERE"
sha256sum -c SHA256SUMS
want=358b3abd8c76f478cab7f8487906715091ab2372de7db0f0a178829597a2b1db
got=$(sha256sum r1_gate_v9.py | awk '{print $1}')
[ "$got" = "$want" ] || { echo "frozen r1_gate_v9.py hash mismatch" >&2; exit 1; }
python3 -m py_compile ./*.py
python3 manifest_selftest.py
python3 gate_selftest.py
python3 verdict_selftest.py
python3 witness_selftest.py
python3 pipeline_selftest.py
python3 freeze_epoch_selftest.py
python3 freeze_epoch.py --epoch-id VERIFY --check-only >/dev/null
printf '%s\n' 'EVIDENCE_PIPELINE_V4_2_VERIFY: PASS (runtime not executed)'
