#!/usr/bin/env python3
"""Verify documentation/provenance contracts against executable code facts."""
from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PIPE = ROOT / 'pipeline'
VALIDATOR = PIPE / 'r1a_manifest.py'
GATE = PIPE / 'r1_gate_v9_1.py'
HOST_C = ROOT / 'host' / 'r1a_host.c'
DOCS = (
    ROOT / 'host' / 'R1A-HARNESS-SPEC.md',
    ROOT / 'host' / 'README.md',
    PIPE / 'README.md',
)
CONTRACT_RE = re.compile(r'<!--\s*R1A_CONTRACT\s+(\{.*?\})\s*-->')
FENCE_RE = re.compile(r'```[^\n]*\n(.*?)```', re.S)


def parse(path):
    return ast.parse(path.read_text(), filename=str(path))


def literal_assignment(path, name):
    tree = parse(path)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == name for t in targets):
            return ast.literal_eval(value)
    raise RuntimeError(f'{path}: missing {name}')


def gate_args():
    out = set()
    for node in ast.walk(parse(GATE)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != 'add_argument' or not node.args:
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if arg.value.startswith('--'):
                    out.add(arg.value)
    return out


def code_contract():
    version = literal_assignment(VALIDATOR, 'MANIFEST_VERSION')
    artifacts = list(literal_assignment(VALIDATOR, 'EPOCH_ARTIFACTS'))
    args = gate_args()
    if '--manifest' not in args:
        raise RuntimeError('gate code no longer exposes --manifest')
    host_src = HOST_C.read_text()
    host_epoch_arg = '--epoch-json' if 'ARG("--epoch-json")' in host_src else 'absent'
    return {
        'manifest_version': version,
        'gate_entry': GATE.name,
        'gate_manifest_arg': '--manifest',
        'gate_harness_arg': '--harness' if '--harness' in args else 'absent',
        'host_epoch_arg': host_epoch_arg,
        'legacy_bridge_trusted': False,
        'epoch_artifacts': artifacts,
    }


def check_doc(path, expected):
    errs = []
    text = path.read_text()
    m = CONTRACT_RE.search(text)
    if not m:
        return [f'{path.relative_to(ROOT)}: missing R1A_CONTRACT block']
    try:
        got = json.loads(m.group(1))
    except Exception as exc:
        return [f'{path.relative_to(ROOT)}: malformed R1A_CONTRACT JSON: {exc}']
    if got != expected:
        errs.append(f'{path.relative_to(ROOT)}: R1A_CONTRACT != code-derived facts')

    # Stale executable/trust-path diagrams are load-bearing documentation bugs.
    # Scan fenced blocks only so historical prose can still explain old versions.
    for idx, block in enumerate(FENCE_RE.findall(text), 1):
        compact = ' '.join(block.split())
        if re.search(r'manifest_to_p4\.py\s*(?:→|->)\s*r1_gate_v9\.py', compact):
            errs.append(f'{path.relative_to(ROOT)}: fenced block {idx} contains old bridge→v9 trust path')
        if re.search(r'r1_gate_v9\.py\b[^\n]*--harness', block):
            errs.append(f'{path.relative_to(ROOT)}: fenced block {idx} invokes frozen v9 with --harness')
        if re.search(r'\bsession\s+manifest\s+v1\b', compact, re.I):
            errs.append(f'{path.relative_to(ROOT)}: fenced block {idx} still labels current session manifest v1')

    # The two documents that show the executable flow must contain the actual
    # gate entry and argument outside the machine-readable comment as well.
    if path.name in ('R1A-HARNESS-SPEC.md', 'README.md') and path.parent.name == 'pipeline':
        if 'r1_gate_v9_1.py' not in text or '--manifest' not in text:
            errs.append(f'{path.relative_to(ROOT)}: does not show v9.1 --manifest flow')
    if path.name == 'R1A-HARNESS-SPEC.md':
        if 'r1_gate_v9_1.py --manifest' not in text:
            errs.append(f'{path.relative_to(ROOT)}: spec does not show v9.1 --manifest flow')
    if path in (ROOT / 'host' / 'R1A-HARNESS-SPEC.md', ROOT / 'host' / 'README.md'):
        if '--epoch-json' not in text:
            errs.append(f'{path.relative_to(ROOT)}: does not document the direct epoch JSON input')
    return errs


def main():
    try:
        expected = code_contract()
    except Exception as exc:
        print('CONTRACT_CHECK: FAIL - code facts:', exc)
        return 1

    errs = []
    for path in DOCS:
        errs.extend(check_doc(path, expected))

    # freeze_epoch must agree with the same runtime contract before docs can PASS.
    r = subprocess.run([sys.executable, str(PIPE / 'freeze_epoch.py'),
                        '--epoch-id', 'CONTRACT-CHECK', '--check-only'],
                       cwd=PIPE, text=True, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)
    if r.returncode != 0:
        errs.append('freeze_epoch runtime contract failed: ' + r.stderr.strip())

    print('CODE FACTS')
    print(json.dumps(expected, indent=2, sort_keys=True))
    for path in DOCS:
        print('OK' if not [e for e in errs if str(path.relative_to(ROOT)) in e] else 'FAIL',
              path.relative_to(ROOT))
    if errs:
        for err in errs:
            print('MISMATCH', err)
        print(f'CONTRACT_CHECK: FAIL ({len(errs)} mismatch(es))')
        return 1
    print(f'CONTRACT_CHECK: PASS ({len(DOCS)} docs + runtime epoch contract)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
