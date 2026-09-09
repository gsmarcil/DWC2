#!/usr/bin/env python3
"""Discriminating controls for holder_log_guard.py.

A gate that only ever refuses has not been shown to detect anything, so the
first case is a log that must pass. Each later case breaks exactly one rule.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
GUARD = HERE / 'holder_log_guard.py'
RULE = 'eshutdown_kills_at_or_before_cutoff_excluding_sync_submit_failures'


def header(**over):
    o = {'event': 'R1A_HOLDER_SESSION', 'phase': 'session',
         'session_id': 's001', 'boot_id': 'b-1', 'mode': 'run',
         'synthetic': False}
    o.update(over)
    return o


def record(seq, **over):
    o = {'event': 'R1A_HOLDER', 'phase': 'campaign', 'session_id': 's001',
         'boot_id': 'b-1', 'device_seq': seq, 'pending_reads': 8,
         'synthetic': False, 'pending_definition': RULE,
         'unresolved_reads': 0, 'kills_after_cutoff': 0,
         'sync_submit_failures': 0}
    o.update(over)
    return o


def write(td, objs, raw=None):
    p = Path(td) / 'e.jsonl'
    if raw is not None:
        p.write_text(raw)
    else:
        p.write_text('\n'.join(json.dumps(o) for o in objs) + '\n')
    return p


def run(p):
    r = subprocess.run([sys.executable, str(GUARD), '--event-log', str(p)],
                       capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


CASES = [
    ('a real campaign log passes',
     lambda: ([header()] + [record(i) for i in (1, 2, 3)], None), 0, 'PASS'),
    ('a synthetic flag anywhere is refused',
     lambda: ([header(), record(1, synthetic=True)], None), 1,
     'fixture marker'),
    ('the selftest event is refused',
     lambda: ([header(), record(1, event='R1A_HOLDER_SELFTEST')], None), 1,
     'fixture marker'),
    ('the selftest phase is refused',
     lambda: ([header(), record(1, phase='selftest')], None), 1,
     'fixture marker'),
    ('a selftest header is refused even with clean records',
     lambda: ([header(mode='selftest_holder'), record(1)], None), 1,
     'fixture marker'),
    ('a stale pending_reads rule on the session header is refused',
     lambda: ([header(pending_definition='old_two_term_rule'), record(1)], None),
     1, 'competing meanings'),
    ('a pending_reads rule this gate does not know is refused',
     lambda: ([header(), record(1, pending_definition='old_two_term_rule')],
              None), 1, 'competing meanings'),
    ('a record with no rule at all is refused',
     lambda: ([header(), {'event': 'R1A_HOLDER', 'phase': 'campaign',
                          'session_id': 's001', 'boot_id': 'b-1',
                          'device_seq': 1, 'pending_reads': 8}], None), 1,
     'omit pending_definition'),
    ('a line that is not JSON is refused',
     lambda: (None, '{"event":"R1A_HOLDER"}\nnot json\n'), 1, 'not JSON'),
    ('two session identities are refused',
     lambda: ([header(), record(1), record(2, session_id='OTHER')], None), 1,
     'session/boot identities'),
    ('a repeated device_seq is refused',
     lambda: ([header(), record(1), record(1)], None), 1,
     'not strictly increasing'),
    ('device_seq going backwards is refused',
     lambda: ([header(), record(2), record(1)], None), 1,
     'not strictly increasing'),
    ('a boolean pending_reads is refused',
     lambda: ([header(), record(1, pending_reads=True)], None), 1,
     'pending_reads is True'),
    ('a negative pending_reads is refused',
     lambda: ([header(), record(1, pending_reads=-1)], None), 1,
     'negative pending_reads'),
    ('an empty log is refused',
     lambda: ([], ''), 1, 'no records at all'),
]


def main() -> int:
    fails = 0
    for name, build, want_rc, want_text in CASES:
        objs, raw = build()
        with tempfile.TemporaryDirectory() as td:
            rc, out = run(write(td, objs, raw))
        ok = rc == want_rc and want_text in out
        fails += not ok
        print('%s %s' % ('ok  ' if ok else 'FAIL', name))
        if not ok:
            print('       wanted rc=%d and %r' % (want_rc, want_text))
            for line in out.strip().splitlines()[:8]:
                print('         %s' % line)
    print()
    if fails:
        print('HOLDER LOG GUARD SELFTEST: %d/%d FAILED' % (fails, len(CASES)))
        return 1
    print('HOLDER LOG GUARD SELFTEST: %d/%d PASS (1 positive, %d fail-closed)'
          % (len(CASES), len(CASES), len(CASES) - 1))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
