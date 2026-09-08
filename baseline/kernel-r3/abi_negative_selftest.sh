#!/bin/sh
# Prove the ABI gate fails closed on a structural layout defect.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
D=$(mktemp -d)
trap 'rm -rf "$D"' EXIT
cp "$HERE/abi_probe.c" "$D/probe.c"
python3 - "$D/probe.c" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text()
needle='\t__le32 gintsts;'
if needle not in s:
    raise SystemExit('injection anchor missing')
s=s.replace(needle, '\tu8 injected_padding_hole;\n'+needle, 1)
p.write_text(s)
PY
set +e
python3 "$HERE/abi_check.py" --probe-src "$D/probe.c" > "$D/out" 2>&1
rc=$?
set -e
cat "$D/out"
printf 'exit status: %d\n' "$rc"
if [ "$rc" -eq 0 ]; then
    echo 'ABI NEGATIVE SELFTEST: FAIL (gate accepted injected hole)'
    exit 1
fi
if ! grep -q 'FAILURE(S)' "$D/out"; then
    echo 'ABI NEGATIVE SELFTEST: FAIL (nonzero without expected structural rejection)'
    exit 1
fi
echo 'ABI NEGATIVE SELFTEST: PASS'
