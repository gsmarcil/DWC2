#!/usr/bin/env python3
"""Freeze the epoch from the exact Python modules the evidence path loads.

There is no hand-maintained local artifact table in this tool.

Authority chain:
  r1a_manifest.py::EPOCH_ARTIFACTS
      defines the complete set of artifact keys that constitute an epoch.
  r1_gate_v9_1.py::runtime_epoch_local_files()
      returns the exact local module files Python resolved for the gate,
      witnesses, validator/parser, frozen v9 engine, and verdict generator.
  EPOCH_ARTIFACTS - runtime local keys
      are external artifacts and become required path arguments dynamically.

Default behavior is fail-closed: no epoch JSON is emitted unless every external
artifact is supplied and hashable.  --allow-partial exists only for inspection;
its output is intentionally rejected by the manifest validator.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import r1a_manifest as manifest_mod
import r1_gate_v9_1 as gate_mod

SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
EPOCH_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$')


class FreezeError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def gate_sibling_import_files() -> set[Path]:
    """Sibling modules imported by the gate, derived from its source AST."""
    gate_path = Path(gate_mod.__file__).resolve()
    try:
        tree = ast.parse(gate_path.read_text(), filename=str(gate_path))
    except Exception as exc:
        raise FreezeError(f'cannot parse gate imports: {exc}') from exc
    modules = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            modules.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module.split('.')[0])
    out = set()
    for module in modules:
        candidate = HERE / f'{module}.py'
        if candidate.is_file():
            out.add(candidate.resolve())
    return out


def derive_contract():
    epoch = tuple(manifest_mod.EPOCH_ARTIFACTS)
    if not epoch or len(epoch) != len(set(epoch)):
        raise FreezeError('invalid EPOCH_ARTIFACTS in manifest validator')
    if not all(isinstance(k, str) and k for k in epoch):
        raise FreezeError('EPOCH_ARTIFACTS contains a non-string/empty key')

    raw_local = gate_mod.runtime_epoch_local_files()
    if not isinstance(raw_local, dict) or not raw_local:
        raise FreezeError('gate runtime_epoch_local_files() returned no mapping')

    local = {}
    for key, value in raw_local.items():
        if not isinstance(key, str) or not key:
            raise FreezeError('gate local map has invalid key')
        p = Path(value).resolve()
        if not p.is_file():
            raise FreezeError(f'local epoch artifact {key} is not a file: {p}')
        # Every local load-bearing tool must resolve beside this frozen gate.
        # This prevents PYTHONPATH/site-packages shadowing from being silently
        # frozen as if it were package-local evidence tooling.
        if p.parent != HERE:
            raise FreezeError(f'local epoch artifact {key} resolved outside package: {p}')
        local[key] = p

    imported = gate_sibling_import_files()
    covered_paths = set(local.values())
    uncovered_imports = imported - covered_paths
    if uncovered_imports:
        raise FreezeError('gate imports sibling modules that are not epoch-hashed: ' +
                          ', '.join(sorted(p.name for p in uncovered_imports)))

    epoch_set = set(epoch)
    local_set = set(local)
    extra = local_set - epoch_set
    if extra:
        raise FreezeError('gate exposes local epoch keys absent from EPOCH_ARTIFACTS: ' +
                          ', '.join(sorted(extra)))

    external = tuple(k for k in epoch if k not in local_set)
    return epoch, local, external


def option_for(key: str) -> str:
    return '--' + key.replace('_', '-')


def build_parser(external):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--epoch-id', required=True)
    for key in external:
        ap.add_argument(option_for(key), dest=key, metavar='PATH',
                        help=f'path for external epoch artifact {key!r}')
    ap.add_argument('-o', '--out', metavar='OUT.json')
    ap.add_argument('--check-only', action='store_true',
                    help='verify the code-derived epoch contract without hashing externals')
    ap.add_argument('--allow-partial', action='store_true',
                    help='emit incomplete JSON for inspection only (not manifest-valid)')
    ap.add_argument('--explain', action='store_true',
                    help='show the derived local/external artifact mapping')
    return ap


def main(argv=None) -> int:
    try:
        epoch, local, external = derive_contract()
    except Exception as exc:
        print(f'EPOCH_CONTRACT_ERROR: {exc}', file=sys.stderr)
        return 2

    a = build_parser(external).parse_args(argv)
    if not EPOCH_ID_RE.fullmatch(a.epoch_id):
        print('EPOCH_FREEZE_REFUSED: --epoch-id must match '
              '[A-Za-z0-9][A-Za-z0-9._:-]{0,127}', file=sys.stderr)
        return 2

    if a.explain or a.check_only:
        print('EPOCH_ARTIFACTS:', ', '.join(epoch), file=sys.stderr)
        for key in epoch:
            if key in local:
                print(f'  local    {key:20s} -> {local[key].name}', file=sys.stderr)
            else:
                print(f'  external {key:20s} -> {option_for(key)}', file=sys.stderr)

    if a.check_only:
        print('EPOCH_CONTRACT: PASS', file=sys.stderr)
        return 0

    missing = [key for key in external if not getattr(a, key)]
    if missing and not a.allow_partial:
        print('EPOCH_FREEZE_REFUSED: missing external artifact paths: ' +
              ', '.join(missing), file=sys.stderr)
        print('supply: ' + ' '.join(f'{option_for(k)} PATH' for k in missing),
              file=sys.stderr)
        return 2

    artifacts = {}
    try:
        for key, path in local.items():
            artifacts[key] = sha256_file(path)
        for key in external:
            value = getattr(a, key)
            if not value:
                continue
            path = Path(value).resolve()
            if not path.is_file():
                raise FreezeError(f'external artifact {key} is not a file: {path}')
            artifacts[key] = sha256_file(path)
    except Exception as exc:
        print(f'EPOCH_FREEZE_ERROR: {exc}', file=sys.stderr)
        return 2

    bad = [key for key, digest in artifacts.items()
           if not SHA256_RE.fullmatch(digest)]
    if bad:
        print('EPOCH_FREEZE_ERROR: malformed digest(s): ' + ', '.join(bad),
              file=sys.stderr)
        return 2

    block = {
        'epoch_id': a.epoch_id,
        'artifacts': {key: artifacts[key] for key in sorted(artifacts)},
    }
    text = json.dumps(block, indent=2, sort_keys=True) + '\n'

    if missing:
        print('WARNING: PARTIAL EPOCH BLOCK; manifest validation will reject it.\n'
              'missing: ' + ', '.join(missing), file=sys.stderr)

    if a.out:
        Path(a.out).write_text(text)
        print(f'wrote {a.out} ({len(artifacts)}/{len(epoch)} artifacts pinned)',
              file=sys.stderr)
    else:
        print(text, end='')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
