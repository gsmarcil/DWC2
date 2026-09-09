#!/usr/bin/env python3
"""Fail-closed Git-tracking proof for an archive checkout without .git.

This is not a replacement for Git when repository metadata is available.  It is
an archive-native proof bound to the authenticated source commit used for this
delivery.  It proves that:

  * baseline/ is exactly the Git subtree tracked by that commit;
  * the root .gitignore is the exact file from that commit; and
  * none of the paths pinned by baseline/SHA256SUMS is ignored by that policy.

The commit/tree binding was established independently before this file was
admitted.  Any byte, path, symlink, or executable-bit drift changes the Git tree
OID and fails closed.
"""
from __future__ import annotations

import hashlib
import os
import stat
import subprocess
import sys
import tempfile
from functools import cmp_to_key
from pathlib import Path

SOURCE_COMMIT = '9df7b1a4f91a10ef575daa4a658a69ec5ce5723f'
SOURCE_ROOT_TREE = 'd3d13da79d5508d851e995be75e6016c41d3fc42'
SOURCE_BASELINE_TREE = '223dd3983955393a9cadcbbf525767ce9a49f459'
SOURCE_GITIGNORE_SHA256 = '2745b86f79b61480805798a31337fe10f62cea79bfcd5aa5d8a044064ef2302a'


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _obj_hash(kind: bytes, data: bytes) -> bytes:
    header = kind + b' ' + str(len(data)).encode('ascii') + b'\0'
    return hashlib.sha1(header + data).digest()


def _cmp_entry(a, b) -> int:
    # Git's base_name_compare(): a directory compares as if its name had a
    # trailing '/'. This matters for prefix-related names.
    na, da = a[0], a[1]
    nb, db = b[0], b[1]
    n = min(len(na), len(nb))
    if na[:n] != nb[:n]:
        return -1 if na[:n] < nb[:n] else 1
    ca = ord('/') if len(na) == n and da else (0 if len(na) == n else na[n])
    cb = ord('/') if len(nb) == n and db else (0 if len(nb) == n else nb[n])
    return (ca > cb) - (ca < cb)


def git_tree_oid(root: Path, *, omit_root_git: bool = False) -> str:
    """Reproduce a Git tree OID directly from filesystem bytes and modes."""
    def walk(path: Path, top: bool) -> bytes:
        entries = []
        with os.scandir(path) as scan:
            for ent in scan:
                if top and omit_root_git and ent.name == '.git':
                    continue
                name = os.fsencode(ent.name)
                p = path / ent.name
                st = ent.stat(follow_symlinks=False)
                if stat.S_ISDIR(st.st_mode):
                    oid = walk(p, False)
                    mode = b'40000'
                    is_dir = True
                elif stat.S_ISLNK(st.st_mode):
                    data = os.fsencode(os.readlink(p))
                    oid = _obj_hash(b'blob', data)
                    mode = b'120000'
                    is_dir = False
                elif stat.S_ISREG(st.st_mode):
                    data = p.read_bytes()
                    oid = _obj_hash(b'blob', data)
                    mode = b'100755' if (st.st_mode & 0o111) else b'100644'
                    is_dir = False
                else:
                    raise RuntimeError(f'unsupported filesystem entry: {p}')
                entries.append((name, is_dir, mode, oid))
        entries.sort(key=cmp_to_key(_cmp_entry))
        body = b''.join(mode + b' ' + name + b'\0' + oid
                        for name, _is_dir, mode, oid in entries)
        return _obj_hash(b'tree', body)
    return walk(root, True).hex()


def pinned_paths(manifest: Path) -> list[str]:
    out = []
    for lineno, raw in enumerate(manifest.read_text().splitlines(), 1):
        if not raw.strip():
            continue
        parts = raw.split(None, 1)
        if len(parts) != 2:
            raise RuntimeError(f'{manifest}:{lineno}: malformed manifest line')
        digest, rel = parts
        rel = rel.strip()
        if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise RuntimeError(f'{manifest}:{lineno}: malformed SHA256')
        rp = Path(rel)
        if rp.is_absolute() or '..' in rp.parts:
            raise RuntimeError(f'{manifest}:{lineno}: unsafe path {rel!r}')
        out.append(rel)
    if not out:
        raise RuntimeError('baseline/SHA256SUMS contains no pinned paths')
    return out


def ignored_pins(root: Path, pins: list[str]) -> list[str]:
    if not shutil_which('git'):
        raise RuntimeError('git executable is required to evaluate ignore policy')
    # Isolated Git metadata makes the check independent of user/global ignore
    # configuration and does not write anything into the repository tree.
    with tempfile.TemporaryDirectory(prefix='dwc2-ignore-proof-') as td:
        env = os.environ.copy()
        env['GIT_CONFIG_NOSYSTEM'] = '1'
        env['GIT_CONFIG_GLOBAL'] = os.devnull
        subprocess.run(['git', 'init', '-q', td], check=True, env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        gitdir = str(Path(td) / '.git')
        fulls = [f'baseline/{rel}' for rel in pins]
        payload = ('\0'.join(fulls) + '\0').encode('utf-8')
        p = subprocess.run(
            ['git', f'--git-dir={gitdir}', f'--work-tree={root}',
             'check-ignore', '--no-index', '-z', '--stdin'],
            env=env, input=payload, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if p.returncode not in (0, 1):
            err = p.stderr.decode('utf-8', 'replace').strip()
            raise RuntimeError(f'git check-ignore batch failed: {err}')
        if p.returncode == 1:
            return []
        return [x.decode('utf-8', 'replace')
                for x in p.stdout.split(b'\0') if x]


def shutil_which(name: str) -> str | None:
    # Local tiny equivalent avoids importing a larger module solely for which().
    for d in os.environ.get('PATH', '').split(os.pathsep):
        p = Path(d or '.') / name
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return None


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else '.').resolve()
    try:
        if not root.is_dir():
            raise RuntimeError(f'not a directory: {root}')
        baseline = root / 'baseline'
        manifest = baseline / 'SHA256SUMS'
        gitignore = root / '.gitignore'
        if not baseline.is_dir() or not manifest.is_file() or not gitignore.is_file():
            raise RuntimeError('baseline/, baseline/SHA256SUMS, or .gitignore is missing')

        got_baseline = git_tree_oid(baseline)
        if got_baseline != SOURCE_BASELINE_TREE:
            raise RuntimeError('baseline Git tree mismatch: '
                               f'{got_baseline} != {SOURCE_BASELINE_TREE}')
        if sha256(gitignore) != SOURCE_GITIGNORE_SHA256:
            raise RuntimeError('.gitignore preimage mismatch')

        pins = pinned_paths(manifest)
        missing = [f'baseline/{p}' for p in pins if not (baseline / p).is_file()]
        if missing:
            raise RuntimeError('pinned paths missing: ' + ', '.join(missing[:8]))
        ignored = ignored_pins(root, pins)
        if ignored:
            raise RuntimeError('pinned paths ignored by canonical policy: ' + ', '.join(ignored[:8]))

        print('ARCHIVE_TRACKING_PROOF: PASS')
        print('  source_commit       ', SOURCE_COMMIT)
        print('  source_root_tree    ', SOURCE_ROOT_TREE)
        print('  baseline_tree       ', got_baseline)
        print('  pinned_paths        ', len(pins))
        print('  pinned_paths_ignored 0')
        return 0
    except Exception as exc:
        print('ARCHIVE_TRACKING_PROOF: FAIL', file=sys.stderr)
        print('  ' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
