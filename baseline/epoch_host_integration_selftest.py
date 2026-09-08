#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PIPE = ROOT / 'pipeline'
HOST = ROOT / 'host' / 'r1a_host'
PY = sys.executable
SCOPE = [
    '--g-dma','1','--g-dma-desc','0','--abi-version','9',
    '--abi-header','112','--abi-record','80','--snapshot-atomic','1',
    '--lost','0','--overlap-count','0',
]


def must(cond, name, detail=''):
    if not cond:
        print('FAIL', name, detail)
        raise SystemExit(1)
    print('PASS', name)


def host_run(epoch, manifest, *extra):
    cmd = [str(HOST), '--selftest', '--epoch-json', str(epoch),
           '--session-id','s','--boot-id','b', *SCOPE,
           '--manifest', str(manifest), *extra]
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE)


def main():
    must(HOST.is_file() and HOST.stat().st_mode & 0o111,
         'host_binary_present', 'run host/VERIFY.sh first')
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        image = td / 'Image'; image.write_bytes(b'image')
        patch = td / 'observer.patch'; patch.write_bytes(b'patch')
        epoch = td / 'epoch.json'
        r = subprocess.run([
            PY, str(PIPE / 'freeze_epoch.py'), '--epoch-id', 'E-INTEGRATION',
            '--image', str(image), '--observer-patch', str(patch),
            '--harness', str(HOST), '-o', str(epoch)],
            cwd=PIPE, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        must(r.returncode == 0, 'freeze_epoch_complete', r.stderr)

        manifest = td / 'manifest.json'
        r = host_run(epoch, manifest)
        must(r.returncode == 0 and manifest.exists(),
             'host_consumes_epoch_json', r.stderr)
        e = json.loads(epoch.read_text())
        m = json.loads(manifest.read_text())
        must(m['epoch'] == e, 'epoch_copied_without_retyping')

        # Mixing the authoritative epoch file with hand-entered hashes is
        # ambiguous and must abort rather than pick precedence.
        r = host_run(epoch, td / 'mixed.json', '--sha-image', '0' * 64)
        must(r.returncode == 2 and 'cannot be mixed' in r.stderr,
             'manual_hash_mix_refused', r.stderr)

        # The epoch's harness hash is an expectation for /proc/self/exe even in
        # selftest mode when --epoch-json is used.
        bad = json.loads(epoch.read_text())
        bad['artifacts']['harness'] = '0' * 64
        badp = td / 'bad-harness.json'; badp.write_text(json.dumps(bad))
        r = host_run(badp, td / 'bad-harness-manifest.json')
        must(r.returncode == 2 and 'does not match the running binary' in r.stderr,
             'wrong_harness_hash_refused', r.stderr)

        # Duplicate JSON keys are not allowed to create an order-dependent
        # epoch interpretation.
        text = epoch.read_text()
        dup = td / 'dup.json'
        dup.write_text(text.replace('{\n', '{\n  "epoch_id": "DUP",\n', 1))
        r = host_run(dup, td / 'dup-manifest.json')
        must(r.returncode == 2 and 'exactly one plain-string epoch_id' in r.stderr,
             'duplicate_epoch_id_refused', r.stderr)

    print('EPOCH_HOST_INTEGRATION_SELFTEST: 6/6 PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
