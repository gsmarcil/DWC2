#!/usr/bin/env python3
"""Check every source citation in a document against a real kernel tree.

No identifier may be used as evidence unless it exists exactly in the supplied
source. A static audit file cannot enforce that -- it is a claim about a check,
not the check. This regenerates the audit from the tree named on the command
line and exits non-zero if any citation does not hold.

Two citation forms are recognised, because the document uses both:

  A   path/to/file.c:1234   <text quoted from that line>
      path/to/file.c:12-14  <text quoted from anywhere in that range>
      (a leading "*" or "#" is allowed, so C and Python comments are audited
      on the same terms as the prose)

  B   /* path/to/file.c:1234 -- any note */
      <the quoted source line, on the next line>
      /* :1249 */                       <- path inherited from the last one
      <the quoted source line>

Comparison collapses whitespace; a trailing "..." marks a deliberate
truncation. When a quote does not match the cited line, the neighbourhood is
searched and the real line number is reported, because "off by two" is the
mistake this actually catches and saying so is more useful than saying no.

A citation with no quote proves nothing and is counted separately rather than
passed silently.

  usage: citation_audit.py /path/to/linux DOC.md [DOC.md ...]
"""
import re
import sys
from pathlib import Path

PATHPAT = (r'(?:drivers|include|kernel|fs|lib|arch|mm|block|net|sound)'
           r'/[\w./+-]+')
FORM_A = re.compile(r'^\s*(?:[*#]\s*)?(?P<path>' + PATHPAT +
                    r'):(?P<a>\d+)(?:-(?P<b>\d+))?(?P<text>.*)$')
FORM_B = re.compile(r'^\s*/\*\s*(?P<path>' + PATHPAT + r')?:?(?P<a>\d+)'
                    r'(?:-(?P<b>\d+))?\s*(?:[-—].*?)?\*/\s*$')
NEAR = 6

# Facts asserted by absence. Each is (needle, path, expected count).
NEGATIVE = [
    ('case USB_RECIP_DEVICE', 'drivers/usb/core/devio.c', 0),
    ('USB_REQ_SET_CONFIGURATION', 'drivers/usb/core/devio.c', 0),
]


def norm(s: str) -> str:
    return ' '.join(s.split()).strip()


def quote_of(s: str) -> str:
    return norm(s).rstrip('.').strip()


def matches(want: str, got: str) -> bool:
    """Does the document's quote hold against the cited source?

    "..." inside a quote is an elision, so `f(... FLAG ...)` means those
    fragments appear on the cited line(s), in that order. Fragments shorter
    than three characters are ignored -- a one-character fragment would match
    almost anything and would turn the audit into decoration.
    """
    pos = 0
    for frag in want.split('...'):
        frag = frag.strip()
        if len(frag) < 3:
            continue
        i = got.find(frag, pos)
        if i < 0:
            return False
        pos = i + len(frag)
    return True


class Tree:
    def __init__(self, root: Path):
        self.root = root
        self.cache: dict[str, list[str]] = {}

    def lines(self, rel: str) -> list[str]:
        if rel not in self.cache:
            f = self.root / rel
            self.cache[rel] = (f.read_text(errors='replace').splitlines()
                               if f.is_file() else [])
        return self.cache[rel]


def check(tree, rel, a, b, want, out):
    """Return 'ok' | 'bare' | 'bad', appending one report line."""
    src = tree.lines(rel)
    tag = '%s:%d%s' % (rel, a, '-%d' % b if b != a else '')
    if not src:
        out.append('  %-46s MISSING  no such file in the tree' % tag)
        return 'bad'
    if a < 1 or b > len(src):
        out.append('  %-46s MISSING  file has %d lines' % (tag, len(src)))
        return 'bad'
    got = norm(' '.join(src[a - 1:b]))
    if not want:
        out.append('  %-46s (no quote) %s' % (tag, got[:58]))
        return 'bare'
    if matches(want, got):
        out.append('  %-46s OK       %s' % (tag, want[:58]))
        return 'ok'
    for d in range(1, NEAR + 1):
        for cand in (a - d, a + d):
            if 1 <= cand <= len(src) and matches(want, norm(src[cand - 1])):
                out.append('  %-46s WRONG LINE  the text cited is at %d'
                           % (tag, cand))
                return 'bad'
    out.append('  %-46s MISMATCH' % tag)
    out.append('      document: %s' % want[:88])
    out.append('      tree:     %s' % got[:88])
    return 'bad'


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    tree = Tree(Path(sys.argv[1]))
    if not (Path(sys.argv[1]) / 'drivers/usb/core/devio.c').is_file():
        print('not a kernel tree: %s' % sys.argv[1], file=sys.stderr)
        return 2

    tally = {'ok': 0, 'bare': 0, 'bad': 0}
    out = []

    for doc in sys.argv[2:]:
        out.append('citations in %s' % doc)
        lines = Path(doc).read_text(encoding='utf-8').splitlines()
        last_path = None
        i = 0
        while i < len(lines):
            line = lines[i]
            mb = FORM_B.match(line)
            if mb:
                rel = mb['path'] or last_path
                if rel:
                    last_path = rel
                    a = int(mb['a'])
                    b = int(mb['b']) if mb['b'] else a
                    nxt = lines[i + 1] if i + 1 < len(lines) else ''
                    q = quote_of(nxt)
                    if q in ('...', '{', '}', '') or q.startswith('/*'):
                        q = ''
                    tally[check(tree, rel, a, b, q, out)] += 1
                    i += 1
                    continue
            ma = FORM_A.match(line)
            if ma:
                rel = ma['path']
                last_path = rel
                a = int(ma['a'])
                b = int(ma['b']) if ma['b'] else a
                tally[check(tree, rel, a, b, quote_of(ma['text']), out)] += 1
            i += 1
        out.append('')

    out.append('negative facts (absence is the claim):')
    for needle, rel, want_n in NEGATIVE:
        f = Path(sys.argv[1]) / rel
        n = f.read_text(errors='replace').count(needle) if f.is_file() else -1
        ok = n == want_n
        if not ok:
            tally['bad'] += 1
        out.append('  %-46s %d occurrence(s), want %d  %s'
                   % ('%s in %s' % (needle, Path(rel).name), n, want_n,
                      'OK' if ok else 'FAIL'))
    out.append('')
    out.append('%d quoted citation(s) verified, %d unquoted, %d FAILED'
               % (tally['ok'], tally['bare'], tally['bad']))
    print('\n'.join(out))
    return 0 if not tally['bad'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
