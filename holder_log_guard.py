#!/usr/bin/env python3
"""Refuse a holder event log that must not reach the merger.

baseline/pipeline/holder_merge.py selects records on ``event`` and ``phase``
and ignores every other field. It therefore cannot see a fixture: a log whose
records carry ``"synthetic": true`` and ``phase: "campaign"`` merges to
HOLDER_CONFIRMED exactly like a real one. The frozen package must not be
edited, so the refusal lives here, ahead of it in the run order:

    python3 holder_log_guard.py --event-log dev-events.jsonl
    python3 baseline/pipeline/holder_merge.py --manifest ... --event-log ...

What this can and cannot do, stated plainly. It makes accidental laundering
impossible -- a fixture cannot be merged by mistake, and a log written by an
older producer whose pending_reads meant something else is refused by name. It
does not stop deliberate laundering: anyone willing to delete the markers can
delete them. The defence against that is that the deletion has to be a separate,
visible act on a file whose sha256 the manifest carries.

`docs/NEXT-EPOCH-HOLDER-MERGER.md` carries the same rules as the change the
next epoch's merger should absorb, at which point this becomes redundant rather
than load-bearing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# The producer stamps the rule it used. A log computed under a different rule
# carries a different number, whatever the field is called, so an unrecognised
# definition is refused rather than merged.
ACCEPTED_DEFINITIONS = {
    'eshutdown_kills_at_or_before_cutoff_excluding_sync_submit_failures',
}

CAMPAIGN_EVENT = 'R1A_HOLDER'
FIXTURE_EVENTS = {'R1A_HOLDER_SELFTEST'}
FIXTURE_PHASES = {'selftest'}
FIXTURE_MODES = {'selftest_holder'}

REQUIRED = (('session_id', str), ('boot_id', str), ('device_seq', int),
            ('pending_reads', int))


def check(path: Path, report: list) -> int:
    try:
        text = path.read_text()
    except OSError as e:
        report.append(('FAIL', 'cannot read %s: %s' % (path, e)))
        return 1

    bad = 0
    records = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            o = json.loads(line)
        except Exception as e:
            report.append(('FAIL', 'line %d is not JSON: %s' % (n, e)))
            bad += 1
            continue
        if not isinstance(o, dict):
            report.append(('FAIL', 'line %d is not an object' % n))
            bad += 1
            continue
        records.append((n, o))

    if not records:
        report.append(('FAIL', 'the log holds no records at all'))
        return bad + 1

    # 1. fixture markers, anywhere in the file
    fixtures = []
    for n, o in records:
        why = []
        if o.get('synthetic'):
            why.append('synthetic:true')
        if o.get('event') in FIXTURE_EVENTS:
            why.append('event:%s' % o.get('event'))
        if o.get('phase') in FIXTURE_PHASES:
            why.append('phase:%s' % o.get('phase'))
        if o.get('mode') in FIXTURE_MODES:
            why.append('mode:%s' % o.get('mode'))
        if why:
            fixtures.append((n, ', '.join(why)))
    if fixtures:
        bad += 1
        report.append(('FAIL', '%d line(s) carry a fixture marker; this log '
                       'was produced by --selftest-holder and is not evidence'
                       % len(fixtures)))
        for n, why in fixtures[:6]:
            report.append(('', '    line %d: %s' % (n, why)))
        if len(fixtures) > 6:
            report.append(('', '    ... and %d more' % (len(fixtures) - 6)))
    else:
        report.append(('ok', 'no fixture marker anywhere in the log'))

    # 2. pending_reads semantics may not conflict anywhere in the JSONL.
    # Session headers do not carry pending_reads and the canonical producer does
    # not stamp a definition there.  If some other writer does declare one on a
    # header (or any other line), it must still be a definition this gate knows.
    # Every campaign record, because it *does* carry pending_reads, must declare
    # the accepted rule explicitly.
    camp = [(n, o) for n, o in records if o.get('event') == CAMPAIGN_EVENT]
    unknown = [(n, o.get('pending_definition')) for n, o in records
               if 'pending_definition' in o and
               o.get('pending_definition') not in ACCEPTED_DEFINITIONS]
    missing = [n for n, o in camp if 'pending_definition' not in o]
    if unknown:
        bad += 1
        report.append(('FAIL', 'the log declares a pending_reads rule this gate '
                       'does not accept; one JSONL may not carry competing '
                       'meanings for the same field'))
        for n, u in unknown[:6]:
            report.append(('', '    line %d: %r' % (n, u)))
    if missing:
        bad += 1
        report.append(('FAIL', 'campaign record(s) omit pending_definition: %s'
                       % ', '.join(map(str, missing[:12]))))
    if camp and not unknown and not missing:
        report.append(('ok', '%d campaign record(s), one accepted rule'
                       % len(camp)))

    # 3. shape of the fields the merger actually reads
    shape = 0
    for n, o in camp:
        for k, t in REQUIRED:
            v = o.get(k)
            if not isinstance(v, t) or isinstance(v, bool):
                report.append(('FAIL', 'line %d: %s is %r, wanted %s'
                               % (n, k, v, t.__name__)))
                shape += 1
        if isinstance(o.get('pending_reads'), int) and o['pending_reads'] < 0:
            report.append(('FAIL', 'line %d: negative pending_reads' % n))
            shape += 1
    if shape:
        bad += 1

    # 4. one session and one boot, sequence strictly increasing
    ids = {(o.get('session_id'), o.get('boot_id')) for _, o in camp}
    if len(ids) > 1:
        bad += 1
        report.append(('FAIL', 'campaign records span %d session/boot '
                       'identities; the merger would abort on this later, and '
                       'a partial log is not repaired by merging it'
                       % len(ids)))
    seqs = [o.get('device_seq') for _, o in camp]
    if seqs != sorted(seqs) or len(set(seqs)) != len(seqs):
        bad += 1
        report.append(('FAIL', 'device_seq is not strictly increasing: %r'
                       % seqs))
    elif camp:
        report.append(('ok', 'one session/boot identity, device_seq 1..%d'
                       % len(seqs) if seqs == list(range(1, len(seqs) + 1))
                       else 'one session/boot identity, device_seq increasing'))

    # 5. make the excluded counts visible rather than buried in the file
    for k in ('unresolved_reads', 'kills_after_cutoff',
              'sync_submit_failures'):
        tot = sum(o.get(k) or 0 for _, o in camp)
        if tot:
            report.append(('note', 'campaign total %s = %d (excluded from '
                           'pending_reads by construction)' % (k, tot)))
    return bad


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--event-log', required=True, type=Path)
    a = ap.parse_args(argv)

    report: list = []
    bad = check(a.event_log, report)
    for tag, line in report:
        print(line if tag == '' else '%-5s %s' % (tag, line))
    print()
    if bad:
        print('HOLDER LOG GUARD: REFUSED (%d rule violation(s))' % bad)
        return 1
    print('HOLDER LOG GUARD: PASS')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
