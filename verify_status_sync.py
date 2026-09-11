#!/usr/bin/env python3
"""Fail-closed guard against status-document drift.

Two silent failure directions are closed here.

1. DECLARED-VS-COMPUTED GATE STATE.

   ``docs/GATE-STATE.md`` and ``docs/CURRENT-CHECKPOINT.md`` declare the
   repository gate verdict in prose.  Nothing previously compared those
   declarations against the verdict ``VERIFY-REPOSITORY.sh`` actually computes,
   so they drifted: both declared a red gate and a blocked holder campaign long
   after the executable gate had gone green.

   A stale RED declaration is not a safe default.  It invites a reader to
   "repair" a blocker that is already closed, and this repository forbids
   repairing provenance by editing pinned bytes.  So declared state that
   disagrees with computed state fails closed in either direction.

   The computed verdict is supplied by the caller, because only the gate can
   compute it.  This checker never decides whether the repository is healthy;
   it decides only whether the documents tell the truth about it.

   Note on self-reference: the computed REPOSITORY_GATE value passed in is the
   verdict of the evidence checks alone, excluding this checker.  That is
   deliberate.  The documents describe the state of the evidence, and this
   meta-check then reports separately on whether they describe it correctly.
   Comparing the documents against a verdict that already included this check
   would be circular and could never fail.

2. PRODUCER HASH/PATH ATTRIBUTION.

   ``docs/PENDING.md`` attributed the preserved pre-holder SHA256 to the
   canonical producer path.  Acting on that text would mean overwriting the
   admitted holder-witness producer with the legacy source that is retained
   precisely because it cannot emit the holder contract.

   Every documented device-producer digest must therefore name the file that
   actually hashes to it.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

# Documents that declare gate state and are held to the computed verdict.
DECLARATION_FILES = (
    'docs/GATE-STATE.md',
    'docs/CURRENT-CHECKPOINT.md',
)

# Keys every declaration file must state, exactly once, and correctly.
REQUIRED_KEYS = (
    'REPOSITORY_BASELINE',
    'SOURCE_FOUNDATION',
    'HOLDER_CAMPAIGN_READINESS',
    'REPOSITORY_GATE',
)

# Device-producer sources whose digests must be attributed to the right path.
PRODUCER_SOURCES = (
    'r1a-device/r1a_ffs_out_v2.c',
    'r1a-device/legacy/r1a_ffs_out_v2.c.pre-holder',
)

SHA256_RE = re.compile(r'\b[0-9a-f]{64}\b')

# Path-like tokens, used to match a cited path on whole-token boundaries.
#
# Substring matching is wrong here and silently inverts the check: the canonical
# basename 'r1a_ffs_out_v2.c' is a prefix of the preserved 'r1a_ffs_out_v2.c
# .pre-holder', so the canonical digest printed under the legacy path would find
# its own basename inside the legacy filename and pass -- the exact mirror of
# the misattribution this check exists to catch.
PATH_TOKEN_RE = re.compile(r'[A-Za-z0-9_./-]+')

# Trees excluded from the attribution scan.
#
# baseline/ is authenticated, pinned by baseline/SHA256SUMS, and may only be
# repaired by re-importing the same archive -- never by editing its bytes.  A
# misattribution found there would therefore deadlock the gate: red, with no
# permitted repair.  It is also imported evidence rather than instruction to a
# reader of this repository, which is what this check protects.  The scan covers
# the documents this repository can actually correct.
EXCLUDED_TREES = ('.git', 'baseline')


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def declared_values(text: str, key: str) -> list[str]:
    """Every declaration of ``key`` in ``text``, as stated values."""
    found = []
    pattern = re.compile(r'^\s*' + re.escape(key) + r'\s*:\s*(\S.*?)\s*$')
    for line in text.splitlines():
        m = pattern.match(line)
        if m:
            found.append(m.group(1))
    return found


def check_declarations(root: Path, computed: dict[str, str]) -> list[str]:
    errors = []
    for rel in DECLARATION_FILES:
        path = root / rel
        if not path.is_file():
            errors.append(f'missing declaration file: {rel}')
            continue
        text = path.read_text(encoding='utf-8')
        for key in REQUIRED_KEYS:
            values = declared_values(text, key)
            if not values:
                errors.append(f'{rel}: does not declare {key}')
                continue
            if len(values) > 1:
                errors.append(
                    f'{rel}: declares {key} {len(values)} times '
                    f'({", ".join(values)}); exactly one declaration required'
                )
                continue
            want = computed[key]
            got = values[0]
            if got != want:
                errors.append(
                    f'{rel}: declares {key}: {got!r} but the gate computed {want!r}'
                )
    return errors


def check_producer_attribution(root: Path) -> list[str]:
    """No document may cite a producer digest next to the wrong path."""
    errors = []

    digest_to_path = {}
    for rel in PRODUCER_SOURCES:
        path = root / rel
        if not path.is_file():
            errors.append(f'missing producer source: {rel}')
            continue
        digest_to_path[sha256(path)] = rel
    if errors:
        return errors

    def cites(owner: str, tokens: set[str]) -> bool:
        """True if some token names ``owner`` on path-segment boundaries.

        A document inside ``r1a-device/`` legitimately writes
        ``legacy/r1a_ffs_out_v2.c.pre-holder``, so a token is accepted when it
        is a suffix of the owner path on segment boundaries, including the bare
        basename.  Matching on segments rather than on raw substrings is what
        keeps ``r1a_ffs_out_v2.c`` from matching inside
        ``r1a_ffs_out_v2.c.pre-holder``.
        """
        owner_parts = owner.split('/')
        for token in tokens:
            parts = token.strip('/').split('/')
            if parts and parts == owner_parts[len(owner_parts) - len(parts):]:
                return True
        return False


    for md in sorted(root.glob('**/*.md')):
        if any(part in EXCLUDED_TREES for part in md.parts):
            continue
        rel_md = md.relative_to(root).as_posix()
        lines = md.read_text(encoding='utf-8').splitlines()
        for idx, line in enumerate(lines):
            for digest in SHA256_RE.findall(line.lower()):
                owner = digest_to_path.get(digest)
                if owner is None:
                    continue
                # The owning path must appear near its digest.  Look back far
                # enough to span a prose sentence plus a fenced code block.
                window = '\n'.join(lines[max(0, idx - 12):idx + 3])
                tokens = set(PATH_TOKEN_RE.findall(window))
                if cites(owner, tokens):
                    continue
                wrong = [
                    other
                    for other in digest_to_path.values()
                    if other != owner and cites(other, tokens)
                ]
                detail = f' (window names {wrong[0]} instead)' if wrong else ''
                errors.append(
                    f'{rel_md}:{idx + 1}: digest {digest[:12]}... belongs to '
                    f'{owner} but that path is not cited near it{detail}'
                )
    return errors


USAGE = (
    'usage: verify_status_sync.py [--root DIR] '
    + ' '.join(f'<{k}>' for k in REQUIRED_KEYS)
)


def main(argv: list[str]) -> int:
    args = argv[1:]
    root = Path(__file__).resolve().parent

    # --root exists so the discriminating controls can drive this checker over
    # fixture trees.  The gate itself never passes it.
    if args and args[0] == '--root':
        if len(args) < 2:
            print('STATUS_SYNC: FAIL', file=sys.stderr)
            print('  ' + USAGE, file=sys.stderr)
            return 2
        root = Path(args[1]).resolve()
        args = args[2:]

    if len(args) != len(REQUIRED_KEYS):
        print('STATUS_SYNC: FAIL', file=sys.stderr)
        print('  ' + USAGE, file=sys.stderr)
        return 2

    computed = dict(zip(REQUIRED_KEYS, args))

    errors = check_declarations(root, computed)
    errors += check_producer_attribution(root)

    if errors:
        print('STATUS_SYNC: FAIL', file=sys.stderr)
        for e in errors:
            print('  ' + e, file=sys.stderr)
        return 1

    print('STATUS_SYNC: PASS')
    for key in REQUIRED_KEYS:
        print(f'  {key:<26} {computed[key]}')
    print(f'  producer_digests_checked   {len(PRODUCER_SOURCES)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
