#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable


def run(root):
    return subprocess.run([PY, 'check_contract.py'], cwd=root, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def must(cond, name, detail=''):
    if not cond:
        print('FAIL', name, detail)
        raise SystemExit(1)
    print('PASS', name)


def copy_root(dst):
    shutil.copytree(ROOT, dst, ignore=shutil.ignore_patterns(
        '__pycache__', '*.pyc', 'r1a_host', 'SHA256SUMS'))


def main():
    r = run(ROOT)
    must(r.returncode == 0 and 'CONTRACT_CHECK: PASS' in r.stdout,
         'current_contract', r.stdout + r.stderr)

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)

        # 1) Machine-readable doc contract mutation.
        x = td / 'doc-contract'
        copy_root(x)
        p = x / 'host' / 'R1A-HARNESS-SPEC.md'
        s = p.read_text().replace('"manifest_version":2', '"manifest_version":1', 1)
        p.write_text(s)
        r = run(x)
        must(r.returncode == 1 and 'R1A_CONTRACT != code-derived facts' in r.stdout,
             'doc_contract_mutation_detected', r.stdout)

        # 2) Re-introduce the old trust-path arrow in a fenced block.
        x = td / 'old-arrow'
        copy_root(x)
        p = x / 'host' / 'R1A-HARNESS-SPEC.md'
        p.write_text(p.read_text() + '\n```text\nmanifest_to_p4.py -> r1_gate_v9.py\n```\n')
        r = run(x)
        must(r.returncode == 1 and 'old bridge' in r.stdout,
             'old_bridge_arrow_detected', r.stdout)

        # 3) Code changes its gate argument: docs must stop passing.
        x = td / 'gate-arg'
        copy_root(x)
        p = x / 'pipeline' / 'r1_gate_v9_1.py'
        s = p.read_text().replace("ap.add_argument('--manifest',action='append',default=[],required=True)",
                                  "ap.add_argument('--harness',action='append',default=[],required=True)", 1)
        p.write_text(s)
        r = run(x)
        must(r.returncode == 1 and ('gate code no longer exposes --manifest' in r.stdout or
                                    'code facts' in r.stdout),
             'gate_arg_drift_detected', r.stdout + r.stderr)

        # 4) Host drops the direct epoch input: docs must stop passing.
        x = td / 'host-epoch-arg'
        copy_root(x)
        p = x / 'host' / 'r1a_host.c'
        s = p.read_text().replace('ARG("--epoch-json")', 'ARG("--epoch-json-removed")', 1)
        p.write_text(s)
        r = run(x)
        must(r.returncode == 1 and 'R1A_CONTRACT != code-derived facts' in r.stdout,
             'host_epoch_arg_drift_detected', r.stdout + r.stderr)

    print('CONTRACT_SELFTEST: 5/5 PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
