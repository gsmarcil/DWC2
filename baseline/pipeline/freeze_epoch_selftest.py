#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable


def run(cwd, *args):
    return subprocess.run([PY, 'freeze_epoch.py', *args], cwd=cwd,
                          text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def must(cond, name, detail=''):
    if not cond:
        print('FAIL', name, detail)
        raise SystemExit(1)
    print('PASS', name)


def main():
    # 1) Current package contract resolves cleanly.
    r = run(HERE, '--epoch-id', 'T', '--check-only')
    must(r.returncode == 0 and 'EPOCH_CONTRACT: PASS' in r.stderr,
         'contract_current', r.stderr)

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        image = td / 'Image'
        patch = td / 'observer.patch'
        harness = td / 'r1a_host'
        image.write_bytes(b'image-v1')
        patch.write_bytes(b'patch-v1')
        harness.write_bytes(b'harness-v1')

        # 2) Missing externals are a hard failure and do not create OUT.
        out = td / 'epoch.json'
        r = run(HERE, '--epoch-id', 'T', '-o', str(out))
        must(r.returncode == 2 and not out.exists() and
             'EPOCH_FREEZE_REFUSED' in r.stderr,
             'missing_externals_fail_closed', r.stderr)

        # 3) Complete freeze pins exactly the validator's artifact set.
        r = run(HERE, '--epoch-id', 'T', '--image', str(image),
                '--observer-patch', str(patch), '--harness', str(harness),
                '-o', str(out))
        must(r.returncode == 0 and out.exists(), 'complete_freeze', r.stderr)
        block = json.loads(out.read_text())
        sys.path.insert(0, str(HERE))
        import r1a_manifest
        must(set(block['artifacts']) == set(r1a_manifest.EPOCH_ARTIFACTS),
             'exact_epoch_keyset')
        must(block['artifacts']['image'] == sha(image) and
             block['artifacts']['observer_patch'] == sha(patch) and
             block['artifacts']['harness'] == sha(harness),
             'external_hashes_from_files')

        # 4) Partial mode is explicit and still structurally incomplete.
        r = run(HERE, '--epoch-id', 'T', '--allow-partial')
        must(r.returncode == 0 and 'PARTIAL EPOCH BLOCK' in r.stderr,
             'partial_is_explicit')
        partial = json.loads(r.stdout)
        must({'image', 'observer_patch', 'harness'} - set(partial['artifacts']) ==
             {'image', 'observer_patch', 'harness'},
             'partial_missing_external_keys')

        # 5) Mutating validator keyset without changing runtime local map fails.
        mutated = td / 'pipeline-validator-drift'
        shutil.copytree(HERE, mutated)
        vp = mutated / 'r1a_manifest.py'
        text = vp.read_text()
        text = text.replace("    'usbmon_verifier',\n", '', 1)
        vp.write_text(text)
        r = run(mutated, '--epoch-id', 'T', '--check-only')
        must(r.returncode == 2 and 'absent from EPOCH_ARTIFACTS' in r.stderr,
             'validator_vs_runtime_map_drift_detected', r.stderr)

        # 6) A new sibling import not added to the epoch is detected.
        mutated = td / 'pipeline-import-drift'
        shutil.copytree(HERE, mutated)
        (mutated / 'dummy_epoch_dependency.py').write_text('VALUE=1\n')
        gp = mutated / 'r1_gate_v9_1.py'
        text = gp.read_text().replace('import r1_verdict as _verdict\n',
                                      'import r1_verdict as _verdict\nimport dummy_epoch_dependency\n', 1)
        gp.write_text(text)
        r = run(mutated, '--epoch-id', 'T', '--check-only')
        must(r.returncode == 2 and 'not epoch-hashed' in r.stderr,
             'new_local_import_requires_epoch_pin', r.stderr)

        # 7) Epoch ids that would require JSON escaping are rejected by the
        # freezer, so the host's deliberately narrow parser never has to guess.
        r = run(HERE, '--epoch-id', 'bad id with spaces', '--check-only')
        must(r.returncode == 2 and '--epoch-id must match' in r.stderr,
             'unsafe_epoch_id_refused', r.stderr)

        # 8) A local file resolving outside the package is refused.  Simulate
        # it by modifying runtime_epoch_local_files() to return /etc/hosts for
        # one existing key; no hashes should be emitted.
        mutated = td / 'pipeline-outside-resolution'
        shutil.copytree(HERE, mutated)
        gp = mutated / 'r1_gate_v9_1.py'
        text = gp.read_text().replace(
            "'verdict_generator': Path(_verdict.__file__).resolve(),",
            "'verdict_generator': Path('/etc/hosts').resolve(),", 1)
        gp.write_text(text)
        r = run(mutated, '--epoch-id', 'T', '--check-only')
        must(r.returncode == 2 and 'resolved outside package' in r.stderr,
             'outside_package_resolution_refused', r.stderr)

    print('FREEZE_EPOCH_SELFTEST: 8/8 PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
