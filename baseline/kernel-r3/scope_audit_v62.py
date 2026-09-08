#!/usr/bin/env python3
"""Scope auditor for the v6.2 R1 observer probes.  (v2)

v1 of this file passed a deliberately defective input -- a false negative.
Cause: stmt_start() treated `if (...)` + unbraced body as ONE statement, so
walking back from the probe skipped straight over the guard it was meant to
detect.  v2 makes an unbraced control header a hard statement boundary,
located by paren-balancing rather than by line shape.

Defect class being hunted (invisible to the compiler):

    if (cond)
            dev_warn(...);      <- unbraced body, ONE statement
            probe();            <- sibling of the `if`, runs ALWAYS

Rule: for each observer probe, if the statement immediately before it is the
sole unbraced body of a control header, the probe escaped that guard -> FLAG.

A flag means "review this site", not "proven wrong": the same shape is legal
when the unbraced body is a return/break/continue/goto and the probe is meant
to run on the fall-through.  Those are reported separately as REVIEW.

Exit non-zero on any FAIL.
"""
import re
import sys

if len(sys.argv) != 2:
    sys.exit('usage: %s path/to/drivers/usb/dwc2/gadget.c\n'
             '(no default: the previous one pointed at the author\'s tree and '
             'was meaningless anywhere else)' % sys.argv[0])
PATH = sys.argv[1]
PROBE = re.compile(r'\bdwc2_r1_[a-z0-9_]+\s*\(')
SKIP = re.compile(r'^\s*(static|void|int|bool|u32|u64|struct|const)\b'
                  r'|debugfs_create|_fops\b|\bdwc2_r1_init\b')
CTRL = re.compile(r'^\s*(\}\s*)?(else\s+if|else|if|for|while)\b')
ESCAPE = re.compile(r'^\s*(return|break|continue|goto)\b')

raw = open(PATH).read().split('\n')


def clean(l):
    s = re.sub(r'"(\\.|[^"\\])*"', '""', l)
    s = re.sub(r"'(\\.|[^'\\])*'", "''", s)
    s = re.sub(r'/\*.*?\*/', '', s)
    return s.split('//')[0].rstrip()


def is_skippable(i):
    s = clean(raw[i]).strip()
    return (not s) or s.startswith('#') or s.startswith('*') \
        or s.startswith('/*')


def prev_code(i):
    i -= 1
    while i >= 0 and is_skippable(i):
        i -= 1
    return i if i >= 0 else None


def ctrl_header_end(i):
    """If line i is the LAST line of an if/for/while/else header whose body
    is NOT braced, return the header's first line index; else None."""
    s = clean(raw[i]).rstrip()
    if not s:
        return None
    if s.strip() == 'else':
        return i
    if not s.endswith(')'):
        return None
    bal = 0
    j = i
    while j >= 0:
        t = clean(raw[j])
        for k in range(len(t) - 1, -1, -1):
            if t[k] == ')':
                bal += 1
            elif t[k] == '(':
                bal -= 1
                if bal == 0:
                    before = t[:k]
                    return j if re.search(r'\b(if|for|while)\s*$', before) \
                        else None
        j -= 1
    return None


def stmt_start(end):
    """First line of the statement whose last line is `end`."""
    i = end
    while i > 0:
        p = prev_code(i)
        if p is None:
            return i
        t = clean(raw[p]).strip()
        if t.endswith((';', '{', '}', ':')):
            return i
        if ctrl_header_end(p) is not None:
            return i
        i = p
    return i


probes = [i for i, l in enumerate(raw)
          if PROBE.search(l) and not SKIP.search(l)]
if not probes:
    sys.exit('no observer probes found in %s' % PATH)

fails = reviews = 0
print('scope audit v2: %s' % PATH)
print('probes found: %d\n' % len(probes))

for p in probes:
    label = clean(raw[p]).strip()[:50]
    pc = prev_code(p)
    verdict, why = 'ok  ', 'preceded by block boundary'

    if pc is None:
        why = 'no preceding code'
    else:
        prev = clean(raw[pc]).strip()
        if prev.endswith(('{', '}', ':')):
            why = 'preceded by block boundary'
        elif prev.endswith(';'):
            s = stmt_start(pc)
            hp = prev_code(s)
            hdr = ctrl_header_end(hp) if hp is not None else None
            if hdr is not None:
                body = clean(raw[s]).strip()
                if ESCAPE.match(body):
                    verdict, reviews = 'REVIEW', reviews + 1
                    why = ('follows unbraced `%s` @%d whose body is `%s` '
                           '- fall-through, verify intent'
                           % (clean(raw[hdr]).strip()[:24], hdr + 1,
                              body[:16]))
                else:
                    verdict, fails = 'FAIL', fails + 1
                    why = ('previous stmt is the UNBRACED body of `%s` @%d '
                           '-> probe is UNCONDITIONAL'
                           % (clean(raw[hdr]).strip()[:28], hdr + 1))
            else:
                why = 'previous stmt is a plain statement'
        else:
            why = 'continuation line'

    print('%-6s line %-5d %-52s %s' % (verdict, p + 1, label, why))

print()
if fails:
    print('SCOPE AUDIT v6.2: %d FAILURE(S), %d for review' % (fails, reviews))
    sys.exit(1)
print('SCOPE AUDIT v6.2: all %d probes correctly scoped (%d for review)'
      % (len(probes), reviews))
