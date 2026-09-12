#!/usr/bin/env python3
"""Complete duplicate census for the authenticated research trees.

``baseline/check_duplicates.py`` is pinned inside the authenticated import and
can only confirm the pairs ``baseline/DUPLICATES.txt`` already lists. Two
failure directions were therefore invisible:

1. UNDECLARED DUPLICATES INSIDE ``baseline/``.
2. CROSS-TREE DUPLICATES, which a checker rooted at ``baseline/`` cannot see.

``baseline/`` is authenticated and may only be repaired by re-importing the same
archive, so neither DUPLICATES.txt nor check_duplicates.py may be edited to
record the missing pairs. That edit would have to be laundered through a
regenerated SHA256SUMS, which is the failure mode ``verify_archive_tracking.py``
exists to catch. The census therefore lives outside that tree and reads the
authenticated declaration read-only.

Declarations are pairs, merged transitively before comparison, because a group
of three identical paths is not covered by two disjoint pairs. Any group of two
or more paths sharing one digest that is not covered is a failure.
"""
from __future__ import annotations

import hashlib
import sys
from collections import defaultdict
from pathlib import Path

SCAN_TREES = ('baseline', 'r1a-host', 'r1a-device')
CANONICAL_DECLARATION = 'baseline/DUPLICATES.txt'
OVERLAY_DECLARATION = 'DUPLICATES-OVERLAY.txt'
ALL_TREES = SCAN_TREES


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(token: str) -> str:
    """Qualify a declared path to the repository namespace.

    baseline/DUPLICATES.txt names 'pipeline/r1a_manifest.py' rather than
    'baseline/pipeline/r1a_manifest.py'. Comparing the token as written against
    a census path would match nothing while still reporting success.
    """
    token = token.strip()
    for tree in ALL_TREES:
        if token == tree or token.startswith(tree + '/'):
            return token
    return 'baseline/' + token


def parse_pairs(path: Path) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    if not path.is_file():
        return pairs
    for lineno, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        parts = [normalize(p) for p in line.split('|') if p.strip()]
        if len(parts) < 2:
            print(f'{path.name}:{lineno}: malformed declaration: {line}', file=sys.stderr)
            raise SystemExit(2)
        head, rest = parts[0], parts[1:]
        pairs.extend((head, other) for other in rest)
    return pairs


def components(pairs: list[tuple[str, str]]) -> list[frozenset[str]]:
    """Transitive closure of declared pairs (union-find)."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for a, b in pairs:
        union(a, b)

    groups: dict[str, set[str]] = defaultdict(set)
    for node in parent:
        groups[find(node)].add(node)
    return [frozenset(v) for v in groups.values()]


def census(root: Path) -> dict[str, list[str]]:
    by_digest: dict[str, list[str]] = defaultdict(list)
    for tree in SCAN_TREES:
        base = root / tree
        if not base.is_dir():
            continue
        for path in sorted(base.rglob('*')):
            if path.is_file():
                by_digest[sha256(path)].append(path.relative_to(root).as_posix())
    return {d: sorted(p) for d, p in by_digest.items() if len(p) > 1}


def run(root: Path, quiet: bool = False) -> int:
    declared = components(parse_pairs(root / CANONICAL_DECLARATION)
                          + parse_pairs(root / OVERLAY_DECLARATION))
    if not declared:
        print('DUPLICATE_CENSUS: FAIL', file=sys.stderr)
        print('  no declarations read; refusing to certify a census', file=sys.stderr)
        return 1

    groups = census(root)
    undeclared = []
    for digest, paths in sorted(groups.items()):
        if any(set(paths) <= set(group) for group in declared):
            if not quiet:
                print(f'DECLARED   {digest[:12]}  {" == ".join(paths)}')
        else:
            undeclared.append((digest, paths))

    present = {p for paths in groups.values() for p in paths}
    for group in declared:
        if len(group) > 1 and not (set(group) & present):
            if not quiet:
                print(f'STALE_DECLARATION  {" == ".join(sorted(group))}', file=sys.stderr)

    for digest, paths in undeclared:
        print(f'UNDECLARED {digest[:12]}  {" == ".join(paths)}', file=sys.stderr)

    total = len(groups)
    if undeclared:
        print(f'DUPLICATE_CENSUS: FAIL ({len(undeclared)} undeclared of {total} group(s))',
              file=sys.stderr)
        return 1
    if not quiet:
        print(f'DUPLICATE_CENSUS: PASS ({total} group(s), all declared)')
    return 0


def selftest() -> int:
    """Discriminating controls.

    The census must reject an undeclared group and accept the same bytes once
    declared. A checker that rejects everything, or nothing, carries no
    information about the property it claims to test. The three-path control
    exists because two disjoint pairs do not cover a group of three.
    """
    import tempfile

    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / 'baseline').mkdir()
        (root / 'r1a-host').mkdir()
        (root / 'baseline' / 'a.bin').write_bytes(b'same')
        (root / 'baseline' / 'b.bin').write_bytes(b'same')
        (root / 'baseline' / 'c.bin').write_bytes(b'same')
        (root / 'baseline' / 'unique.bin').write_bytes(b'different')
        (root / 'r1a-host' / 'a.bin').write_bytes(b'same')

        if run(root, quiet=True) == 0:
            print('SELFTEST FAIL: census certified with no declarations', file=sys.stderr)
            failures += 1

        (root / 'baseline' / 'DUPLICATES.txt').write_text('a.bin | b.bin\n')
        if run(root, quiet=True) == 0:
            print('SELFTEST FAIL: partially declared group accepted', file=sys.stderr)
            failures += 1

        (root / 'baseline' / 'DUPLICATES.txt').write_text('a.bin | b.bin | c.bin\n')
        if run(root, quiet=True) == 0:
            print('SELFTEST FAIL: undeclared cross-tree group accepted', file=sys.stderr)
            failures += 1

        (root / 'DUPLICATES-OVERLAY.txt').write_text('baseline/a.bin | r1a-host/a.bin\n')
        if run(root, quiet=True) != 0:
            print('SELFTEST FAIL: fully declared census rejected', file=sys.stderr)
            failures += 1

        if 'baseline/unique.bin' in {p for paths in census(root).values() for p in paths}:
            print('SELFTEST FAIL: unique file reported as duplicate', file=sys.stderr)
            failures += 1

        (root / 'DUPLICATES-OVERLAY.txt').write_text(
            'baseline/a.bin | r1a-host/a.bin\nbaseline/gone1 | baseline/gone2\n')
        if run(root, quiet=True) != 0:
            print('SELFTEST FAIL: stale declaration made census fatal', file=sys.stderr)
            failures += 1

    if failures:
        print(f'DUPLICATE_CENSUS_SELFTEST: FAIL ({failures})', file=sys.stderr)
        return 1
    print('DUPLICATE_CENSUS_SELFTEST: PASS (6/6 controls)')
    return 0


def main(argv: list[str]) -> int:
    if len(argv) > 1 and argv[1] == 'selftest':
        return selftest()
    root = Path(argv[1]).resolve() if len(argv) > 1 else Path(__file__).resolve().parent.parent
    return run(root)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
