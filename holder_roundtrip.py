#!/usr/bin/env python3
"""Round-trip the emitter's real output through the repository's real merger.

The producer is not asked to describe itself. It is built from the source in
this tree, run, and its output is fed to the frozen
baseline/pipeline/holder_merge.py and baseline/pipeline/r1a_manifest.py. Each
negative case breaks exactly one thing and requires the chain to stop.

THE FIXTURE IS NOT IN THE CAMPAIGN NAMESPACE. --selftest-holder writes
event "R1A_HOLDER_SELFTEST" with phase "selftest", which the merger's own
filter drops, so a fixture cannot merge to HOLDER_CONFIRMED by accident. The
first control proves exactly that. To still test the record shape against the
real merger, `promote()` below rewrites a copy into the campaign namespace --
in this test file, visibly, one function, never in the producer.

SCOPE. Every log here is synthetic: its counters are driven by the harness
rather than by an endpoint. This shows the record shape, the identity binding,
the ordering and the counting rules are right. It shows nothing about queue
depth on a board.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else HERE
PIPE = REPO / 'baseline' / 'pipeline'
PRODUCER = REPO / 'r1a-device' / 'r1a_ffs_out_v2.c'
GUARD = REPO / 'holder_log_guard.py'
DEPTH = 8
# Each synthetic round kills DEPTH-1 reads at or before the cutoff, leaves one
# unresolved, and kills one re-armed read after the cutoff. Only the first
# group may be counted.
PENDING = DEPTH - 1
BUILD = tempfile.mkdtemp(prefix='r1a-holder-build-')
BIN = Path(BUILD) / 'r1a_ffs_out_v2'

sys.path.insert(0, str(PIPE))
from fixtures import manifest, sha          # noqa: E402

BOOT = Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def produce(td, n, phase='campaign', session='s001', extra=(), log='e.jsonl'):
    """Run the real emitter and return (rc, stdout+stderr, log path)."""
    ev = Path(td) / log
    cmd = [str(BIN), '--selftest-holder', str(n), '--event-log', str(ev),
           '--depth', str(DEPTH)]
    if session is not None:
        cmd += ['--session-id', session]
    if phase is not None:
        pf = Path(td) / 'phase'
        pf.write_text(phase + '\n')
        cmd += ['--phase-file', str(pf)]
    cmd += list(extra)
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr, ev


def promote(ev, out, keep_synthetic=False):
    """Rewrite a fixture into the campaign namespace, in the test only.

    Each record's phase becomes the phase the marker file actually named, so a
    fixture marked "preflight" promotes to a preflight record and still finds
    no campaign events. This is what the producer would have written in a real
    run; it is not something the producer can do.
    """
    lines = []
    for line in Path(ev).read_text().splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        if o.get('event') == 'R1A_HOLDER_SELFTEST':
            o['event'] = 'R1A_HOLDER'
            o['phase'] = o.get('phase_marker', 'unknown')
        if not keep_synthetic:
            o.pop('synthetic', None)
            # The session header declares the fixture mode too, and
            # holder_log_guard.py refuses a log whose header still says so.
            # A faithful promotion has to clear that as well; a sloppy one is
            # caught, which is a control of its own below.
            if o.get('mode') == 'selftest_holder':
                o['mode'] = 'run'
        lines.append(json.dumps(o))
    Path(out).write_text('\n'.join(lines) + '\n')
    return Path(out)


def merged(td, ev, n, floor=1, session='s001', boot=None, name='merged.json'):
    """Run the frozen merger exactly as the pipeline README runs it."""
    m = manifest(session, sha('d'), n)
    m['session']['boot_id'] = boot if boot is not None else BOOT
    mp = Path(td) / 'manifest.json'
    mp.write_text(json.dumps(m, indent=2, sort_keys=True))
    out = Path(td) / name
    p = subprocess.run([sys.executable, str(PIPE / 'holder_merge.py'),
                        '--manifest', str(mp), '--event-log', str(ev),
                        '--floor', str(floor), '-o', str(out)],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr, out


def guard(ev):
    p = subprocess.run([sys.executable, str(GUARD), '--event-log', str(ev)],
                       capture_output=True, text=True)
    return p.returncode, p.stdout + p.stderr


CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn))
        return fn
    return deco


@case('a fixture log cannot merge as a campaign')
def c1(td):
    rc, out, ev = produce(td, 3)
    assert rc == 0, out
    rc, out, _ = merged(td, ev, 3)
    if rc == 0 or 'HOLDER_CONFIRMED' in out:
        return 'the frozen merger accepted a fixture: %r' % out.strip()
    if '0/3' not in out:
        return 'expected no campaign events, got %r' % out.strip()
    return None


@case('holder_log_guard.py refuses a fixture log')
def c2(td):
    rc, out, ev = produce(td, 3)
    assert rc == 0, out
    rc, out = guard(ev)
    if rc == 0 or 'fixture marker' not in out:
        return 'guard passed a fixture: %r' % out.strip()
    return None


@case('the promoted record shape is accepted by the frozen merger')
def c3(td):
    rc, out, ev = produce(td, 3)
    assert rc == 0, out
    pev = promote(ev, Path(td) / 'promoted.jsonl')
    rcg, outg = guard(pev)
    if rcg != 0:
        return 'guard refused a promoted log:\n' + outg
    rc, out, mp = merged(td, pev, 3)
    if rc != 0 or 'HOLDER_CONFIRMED' not in out:
        return 'merger said %r (rc=%d)' % (out.strip(), rc)
    h = json.loads(mp.read_text())['holder']
    if h['device_teardowns_seen'] != 3 or h['attempts_fired'] != 3:
        return 'paired %r' % h
    if h['extra_teardowns'] != 0 or h['meets_floor_count'] != 3:
        return 'floor %r' % h
    if [r['pending_reads'] for r in h['attempts']] != [PENDING] * 3:
        return 'depths %r' % h['attempts']
    if [r['device_seq'] for r in h['attempts']] != [1, 2, 3]:
        return 'sequence %r' % h['attempts']
    return None


@case('the merged manifest still validates against the frozen validator')
def c4(td):
    rc, out, ev = produce(td, 2)
    assert rc == 0, out
    pev = promote(ev, Path(td) / 'promoted.jsonl')
    rc, out, mp = merged(td, pev, 2)
    assert rc == 0, out
    p = subprocess.run([sys.executable, str(PIPE / 'r1a_manifest.py'),
                        str(mp)], capture_output=True, text=True)
    if p.returncode != 0:
        return 'validator rejected the merged manifest:\n' + p.stdout + p.stderr
    return None


@case('every fixture record is outside the campaign namespace and flagged')
def c5(td):
    rc, out, ev = produce(td, 2)
    assert rc == 0, out
    lines = [json.loads(l) for l in ev.read_text().splitlines() if l.strip()]
    if lines[0].get('event') != 'R1A_HOLDER_SESSION':
        return 'no session header'
    if lines[0].get('mode') != 'selftest_holder':
        return 'header does not declare the fixture mode: %r' % lines[0]
    if 'pending_definition' in lines[0]:
        return 'session header carries count semantics it does not own: %r' % lines[0]
    if not all(l.get('synthetic') is True for l in lines):
        return 'a record is not marked synthetic'
    body = lines[1:]
    if any(l['event'] != 'R1A_HOLDER_SELFTEST' for l in body):
        return 'a fixture record uses the campaign event name'
    if any(l['phase'] != 'selftest' for l in body):
        return 'a fixture record uses a campaign-space phase'
    return None


@case('pending_reads excludes unresolved reads and post-cutoff kills')
def c6(td):
    rc, out, ev = produce(td, 3)
    assert rc == 0, out
    recs = [json.loads(l) for l in ev.read_text().splitlines() if l.strip()][1:]
    for r in recs:
        if r['pending_reads'] != PENDING:
            return 'pending_reads %r, wanted %d' % (r['pending_reads'], PENDING)
        if r['unresolved_reads'] != 1:
            return 'the unresolved read was not reported: %r' % r
        if r['kills_after_cutoff'] != 1:
            return 'the post-cutoff kill was not reported: %r' % r
        if 'cutoff' not in r['pending_definition']:
            return 'the rule is not stamped on the record: %r' % r
    return None


@case('a non-campaign phase marker yields no campaign events')
def c7(td):
    rc, out, ev = produce(td, 3, phase='preflight')
    assert rc == 0, out
    pev = promote(ev, Path(td) / 'promoted.jsonl')
    if any(json.loads(l).get('phase') == 'campaign'
           for l in pev.read_text().splitlines() if l.strip()):
        return 'a preflight fixture promoted into the campaign phase'
    rc, out, _ = merged(td, pev, 3)
    if rc == 0 or 'HOLDER_BELOW_FLOOR' not in out:
        return 'accepted preflight records as campaign: %r' % out.strip()
    return None


@case('a phase token outside the vocabulary is refused, not passed through')
def c8(td):
    rc, out, ev = produce(td, 2, phase='Campaign')
    if rc != 0:
        return 'producer failed: %s' % out
    if 'not in the vocabulary' not in out:
        return 'producer accepted a near-miss token silently: %r' % out
    recs = [json.loads(l) for l in ev.read_text().splitlines() if l.strip()][1:]
    if any(r['phase_marker'] != 'unknown' for r in recs):
        return 'record kept a rejected token: %r' % recs
    return None


@case('a different session_id in the manifest stops the merge')
def c9(td):
    rc, out, ev = produce(td, 2, session='s001')
    assert rc == 0, out
    pev = promote(ev, Path(td) / 'promoted.jsonl')
    rc, out, _ = merged(td, pev, 2, session='OTHER')
    if rc != 2 or 'HOLDER INPUT ERROR' not in out:
        return 'merger did not refuse a foreign session: %r' % out.strip()
    return None


@case('a different boot_id in the manifest stops the merge')
def c10(td):
    rc, out, ev = produce(td, 2)
    assert rc == 0, out
    pev = promote(ev, Path(td) / 'promoted.jsonl')
    rc, out, _ = merged(td, pev, 2, boot='b-1111')
    if rc != 2 or 'HOLDER INPUT ERROR' not in out:
        return 'merger did not refuse a foreign boot: %r' % out.strip()
    return None


@case('a missing teardown record is not paired away')
def c11(td):
    rc, out, ev = produce(td, 3)
    assert rc == 0, out
    pev = promote(ev, Path(td) / 'promoted.jsonl')
    lines = [l for l in pev.read_text().splitlines() if l.strip()]
    pev.write_text('\n'.join(lines[:-1]) + '\n')
    rc, out, _ = merged(td, pev, 3)
    if rc == 0 or 'HOLDER_BELOW_FLOOR' not in out:
        return 'merger accepted 2 records for 3 attempts: %r' % out.strip()
    return None


@case('an extra campaign teardown is not attributed')
def c12(td):
    rc, out, ev = produce(td, 4)
    assert rc == 0, out
    pev = promote(ev, Path(td) / 'promoted.jsonl')
    rc, out, mp = merged(td, pev, 3)
    if rc == 0:
        return 'merger accepted 4 records for 3 attempts: %r' % out.strip()
    h = json.loads(mp.read_text())['holder'] if mp.exists() else {}
    if h and h.get('extra_teardowns') != 1:
        return 'extra not counted: %r' % h
    return None


@case('a floor above the counted depth is refused')
def c13(td):
    rc, out, ev = produce(td, 2)
    assert rc == 0, out
    pev = promote(ev, Path(td) / 'promoted.jsonl')
    rc, out, _ = merged(td, pev, 2, floor=PENDING + 1)
    if rc == 0 or 'HOLDER_BELOW_FLOOR' not in out:
        return 'merger met a floor it should not: %r' % out.strip()
    rc, out, _ = merged(td, pev, 2, floor=PENDING, name='m2.json')
    if rc != 0 or 'HOLDER_CONFIRMED' not in out:
        return 'merger missed a floor it should meet: %r' % out.strip()
    return None


@case('the guard still refuses a promotion that kept the synthetic flag')
def c14(td):
    rc, out, ev = produce(td, 2)
    assert rc == 0, out
    pev = promote(ev, Path(td) / 'sloppy.jsonl', keep_synthetic=True)
    rc, out = guard(pev)
    if rc == 0 or 'fixture marker' not in out:
        return 'guard passed a half-scrubbed fixture: %r' % out.strip()
    return None


@case('the producer refuses a stale log rather than poisoning the merge')
def c15(td):
    rc, out, ev = produce(td, 2)
    assert rc == 0, out
    rc2, out2, _ = produce(td, 2)
    if rc2 == 0:
        return 'producer appended to a non-empty log without being told to'
    if 'already holds' not in out2:
        return 'wrong refusal: %r' % out2
    rc3, out3, _ = produce(td, 2, extra=('--event-log-append',))
    if rc3 != 0:
        return '--event-log-append did not permit the continuation: %s' % out3
    return None


@case('the producer refuses to emit without a session identity')
def c16(td):
    rc, out, _ = produce(td, 2, session=None)
    if rc == 0 or 'session-id' not in out:
        return 'producer emitted a log with no session identity: %r' % out
    return None


@case('the producer refuses a session_id that could break the JSON')
def c17(td):
    rc, out, _ = produce(td, 2, session='a"b')
    if rc == 0 or 'printable token' not in out:
        return 'producer accepted a quote in the session id: %r' % out
    return None


@case('boot_id is read from the kernel, not from the command line')
def c18(td):
    rc, out, ev = produce(td, 1)
    assert rc == 0, out
    recs = [json.loads(l) for l in ev.read_text().splitlines() if l.strip()]
    if any(r['boot_id'] != BOOT for r in recs):
        return 'boot_id is not the running kernel identity'
    p = subprocess.run([str(BIN), '--selftest-holder', '1', '--event-log',
                        str(Path(td) / 'x.jsonl'), '--session-id', 's001',
                        '--boot-id', BOOT], capture_output=True, text=True)
    if p.returncode == 0:
        return 'producer accepted a --boot-id override'
    return None


def build() -> str:
    """Build the producer from the source in the repository, not from a
    checked-in binary: the point is to test the source this tree carries."""
    cc = shutil.which('cc') or shutil.which('gcc')
    if not cc:
        return 'no C compiler'
    p = subprocess.run([cc, '-O2', '-Wall', '-Wextra', '-Werror',
                        '-o', str(BIN), str(PRODUCER)],
                       capture_output=True, text=True)
    if p.returncode != 0:
        return 'producer does not build:\n' + p.stdout + p.stderr
    return ''


def main() -> int:
    if not PRODUCER.is_file():
        print('no producer at %s' % PRODUCER)
        return 2
    if not GUARD.is_file():
        print('no guard at %s' % GUARD)
        return 2
    why = build()
    if why:
        print('HOLDER ROUND-TRIP: cannot run -- %s' % why)
        return 2
    fails = 0
    for name, fn in CASES:
        with tempfile.TemporaryDirectory() as td:
            try:
                why = fn(td)
            except AssertionError as e:
                why = 'setup failed: %s' % e
        print('%s %s' % ('ok  ' if why is None else 'FAIL', name))
        if why is not None:
            fails += 1
            for line in str(why).strip().splitlines()[:10]:
                print('       %s' % line)
    print()
    if fails:
        print('HOLDER ROUND-TRIP: %d/%d FAILED' % (fails, len(CASES)))
        return 1
    print('HOLDER ROUND-TRIP: %d/%d PASS' % (len(CASES), len(CASES)))
    print('format, identity and counting rules only -- no runtime depth is '
          'claimed')
    return 0


def cleanup():
    shutil.rmtree(BUILD, ignore_errors=True)


if __name__ == '__main__':
    try:
        rc = main()
    finally:
        cleanup()
    raise SystemExit(rc)
