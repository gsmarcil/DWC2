#!/usr/bin/env python3
"""Prove the rules that exist twice agree, exhaustively.

Two decisions are implemented in both r1a_host.c (which decides whether a
campaign runs at all) and r1a_manifest.py (which decides whether the resulting
session may be used):

    the re-arm verdict          rearm_verdict()  / derive_rearm()
    the denominator verdict     kwindow_derive() / derive_window()

Drift between a pair would let a session be accepted downstream that the
harness itself refused to run. The failure would be silent and would look like
a result. So the C copy emits its whole table and this diffs it row by row,
rather than either side asserting equivalence.

  usage: rule_crosscheck.py /path/to/r1a_host
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from r1a_manifest import derive_rearm, derive_window, CAP_DMA

# Must match the F[6][3] table in --dump-window-table.
FIELDS = [(100, 140, 146), (100, 140, 139), (100, 141, 146),
          (100, 140, 150), (100, 140, 140), (100, 100, 100)]


def table(binary, flag):
    out = subprocess.run([binary, flag], capture_output=True, text=True,
                         timeout=120)
    if out.returncode != 0:
        raise SystemExit('%s %s exited %d' % (binary, flag, out.returncode))
    rows = [l.split() for l in out.stdout.splitlines() if l.strip()]
    if not rows:
        raise SystemExit('%s %s emitted no table' % (binary, flag))
    return rows


def check_rearm(binary):
    bad = 0
    rows = table(binary, '--dump-rearm-table')
    for perf, base, c, n, r, verdict, disc in rows:
        got = derive_rearm(perf == '1', base == '1', int(c), int(n), int(r))
        want = (verdict, disc == '1')
        if got != want:
            bad += 1
            if bad <= 6:
                print('  rearm differs at performed=%s baseline=%s C=%s N=%s '
                      'R=%s: C says %r, python says %r'
                      % (perf, base, c, n, r, want, got))
    print('  re-arm verdict      %4d rows  %s'
          % (len(rows), 'PASS' if not bad else '%d DIFFER' % bad))
    return bad


def check_window(binary):
    bad = 0
    rows = table(binary, '--dump-window-table')
    for g, lo, at, fi, si, sa, bv, bi, code in rows:
        g, lo, at, fi = int(g), int(lo), int(at), int(fi)
        snaps = []
        for j in range(3):
            snaps.append({
                'ok': True,
                'target': [0, 0, 0, 0],
                'caps_flags': CAP_DMA,
                'snapshot_atomic': at if j == 2 else 1,
                'reset_generation': 8 if (g and j == 1) else 7,
                'lost': 1 if (lo and j == 2) else 0,
                'field_value': FIELDS[fi][j],
            })
        got = derive_window(snaps, 'candidate_cfg0_seen',
                            int(si), int(sa), int(bv), int(bi))[0]
        if got != code:
            bad += 1
            if bad <= 6:
                print('  window differs at gen=%d lost=%d atomic=%d f=%d '
                      'sens=%s/%s B=%s/%s: C says %s, python says %s'
                      % (g, lo, at, fi, si, sa, bv, bi, code, got))
    print('  denominator verdict %4d rows  %s'
          % (len(rows), 'PASS' if not bad else '%d DIFFER' % bad))
    return bad


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    binary = sys.argv[1]
    if not Path(binary).is_file():
        print('RULE CROSSCHECK: cannot run, %s is not a file' % binary,
              file=sys.stderr)
        return 2
    bad = check_rearm(binary) + check_window(binary)
    print('RULE CROSSCHECK: %s' % ('PASS' if not bad else 'FAILED'))
    return 0 if not bad else 1


if __name__ == '__main__':
    raise SystemExit(main())
