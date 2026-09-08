#!/usr/bin/env python3
"""Emit the R1A verdict document from evidence, not from typing.

Every number in the finished text comes from a validated manifest or from the
P4 gate's own JSON. Nothing is retyped, because the one thing a verdict must
never do is state a denominator its evidence does not carry.

Refuses to emit when:
  * any manifest fails r1a_manifest.validate()
  * manifests disagree about the epoch or the mode
  * the gate's mode disagrees with the manifests'
  * the gate verdict is not one this template knows how to phrase

  usage: r1_verdict.py --gate gate.json --manifest s1.json [--manifest s2.json]
                       [--out verdict.md]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from r1a_manifest import validate

# --------------------------------------------------------------- vocabulary
#
# Frozen. A verdict may only be phrased in these terms, and each carries a
# fixed reading that the prose is not allowed to soften or strengthen.
POSITIVE = {
    'R1_PROVEN':
        ('R1 is established on this configuration.',
         'A natural GOUTNAKEFF timeout occurred with the frozen post-timeout '
         'predicate fully satisfied, on a stop owned by the setup that was '
         'open at the time. One such record closes R1; the count does not '
         'matter.'),
    'R1_DELAYED_DISABLE_CORRELATED':
        ('R1 is NOT established. A delayed-status disable correlates in time.',
         'The observer had a delayed-status window open when the stop began. '
         'That is temporal correlation, not causal proof: no cookie crosses '
         'into the function driver, so nothing ties this stop to that setup '
         'beyond the window being open.'),
    'R1_DELAYED_DEQUEUE_CORRELATED':
        ('R1 is NOT established. A delayed-status dequeue correlates in time.',
         'Same reading as the disable variant, on the ep_dequeue path. It may '
         'not be promoted to a causal claim by repetition: the '
         'f_mass_storage worker is signalled before fsg_set_alt() returns, so '
         'the window can open after the dequeue it would be credited with.'),
}

NEGATIVE = 'NEGATIVE_RESULT_VALID_NOT_OBSERVED_ON_TESTED_CONFIGURATION'

OTHER = {
    'TIMEOUT_OBSERVED_R1_NOT_MET':
        ('A timeout occurred but the frozen predicate was not met.',
         'This is neither a positive nor a negative result. The record must '
         'be classified before the campaign continues.'),
    'INCONCLUSIVE_AMBIGUOUS_TIMEOUTS_PRESENT':
        ('Inconclusive: unattributable timeouts are present.',
         'Records classified OVERLAP or UNATTRIBUTED exist in this evidence. '
         'A negative result may not be read past them.'),
    'INSUFFICIENT_CANDIDATES':
        ('Inconclusive: the observer denominator did not reach the threshold.',
         'Not a negative result. The campaign has not yet tested enough.'),
    'PENDING_HARNESS_SENSITIVITY':
        ('Inconclusive: harness sensitivity was not established.',
         'Without it an absence of timeouts is uninterpretable.'),
}


def die(msg: str) -> None:
    print('REFUSING TO EMIT A VERDICT: %s' % msg, file=sys.stderr)
    raise SystemExit(1)


def rule_of_three(b: int) -> str:
    """Display-only upper bound, with the assumption it rests on stated."""
    if b < 1:
        return 'not applicable (no valid attempts)'
    return ('roughly %.2g per attempt as a 95%% upper bound (3/%d), and only '
            'if attempts are independent and equally likely to trigger -- '
            'which attempts inside one boot are not' % (3.0 / b, b))


def sha256_file(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):
            h.update(b)
    return h.hexdigest()


def load_manifests(paths):
    out = []
    for p in paths:
        try:
            m = json.loads(Path(p).read_text())
        except (OSError, ValueError) as e:
            die('manifest %s unreadable: %s' % (p, e))
        errs = validate(m)
        if errs:
            die('manifest %s is not usable:\n  - %s'
                % (p, '\n  - '.join(errs)))
        out.append((str(p), m, sha256_file(p)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--gate', required=True,
                    help="r1_gate_v9.py --json output")
    ap.add_argument('--manifest', action='append', required=True)
    ap.add_argument('--out')
    a = ap.parse_args()

    try:
        g = json.loads(Path(a.gate).read_text())
    except (OSError, ValueError) as e:
        die('gate output unreadable: %s' % e)

    verdict = g.get('verdict')
    if not verdict:
        die('gate output has no verdict')

    mans = load_manifests(a.manifest)

    epochs = {m['epoch']['epoch_id'] for _, m, _ in mans}
    if len(epochs) != 1:
        die('manifests span %d epochs (%s). Evidence from different epochs is '
            'not aggregated: a tool change resets the count.'
            % (len(epochs), ', '.join(sorted(epochs))))
    epoch = epochs.pop()

    modes = {m['session']['mode'] for _, m, _ in mans}
    if len(modes) != 1:
        die('manifests span several modes (%s); one verdict covers one branch'
            % ', '.join(sorted(modes)))
    mode = modes.pop()
    if g.get('mode') and g['mode'] != mode:
        die('the gate ran mode %r but the manifests are mode %r'
            % (g['mode'], mode))

    by_sha={sha:(path,m) for path,m,sha in mans}
    if verdict == NEGATIVE:
        batches=g.get('batches')
        if not isinstance(batches,list) or len(batches)!=len(mans):
            die('negative gate output does not bind one batch to each manifest')
        seen=set()
        for b in batches:
            ms=b.get('manifest_sha256')
            if ms not in by_sha:
                die('gate batch manifest_sha256 does not name a supplied manifest')
            if ms in seen:
                die('gate repeats one manifest batch')
            seen.add(ms)
            path,m=by_sha[ms]
            if b.get('trace_sha256') != m['artifacts']['dump']['sha256']:
                die('gate batch trace sha does not match manifest dump')
            if b.get('host_attempts') != m['denominator']['B_valid']:
                die('gate batch host_attempts does not match manifest B_valid')
            if b.get('denominator') != m['kernel_window']['campaign']['delta']:
                die('gate batch denominator does not match measured campaign delta')
    elif verdict in POSITIVE or verdict.startswith('R1_DELAYED_'):
        ms=g.get('manifest_sha256')
        if ms not in by_sha:
            die('positive/correlated gate result is not bound to a supplied manifest')
        _,m=by_sha[ms]
        if g.get('trace_sha256') != m['artifacts']['dump']['sha256']:
            die('positive/correlated gate trace sha does not match manifest dump')

    boots = {m['session']['boot_id'] for _, m, _ in mans}
    b_valid = sum(m['denominator']['B_valid'] for _, m, _ in mans)
    b_invalid = sum(m['denominator']['B_invalid'] for _, m, _ in mans)
    if verdict == NEGATIVE and b_valid < 1:
        die('negative verdict with B_valid=0 is meaningless and is refused')
    if verdict == NEGATIVE and g.get('host_attempts') != b_valid:
        die('gate host_attempts does not equal the validated manifest total')
    reasons: dict[str, int] = {}
    for _, m, _ in mans:
        for k, v in m['denominator']['invalid_reasons'].items():
            reasons[k] = reasons.get(k, 0) + v

    kernel_denom = g.get('candidates')
    known = verdict in POSITIVE or verdict == NEGATIVE or verdict in OTHER
    if not known:
        die('gate verdict %r has no frozen phrasing. Add one deliberately '
            'rather than letting the document improvise.' % verdict)

    L = []
    w = L.append

    w('# R1A verdict -- %s' % mode)
    w('')
    w('```text')
    w('verdict            %s' % verdict)
    w('epoch              %s' % epoch)
    w('branch             %s' % mode)
    w('sessions           %d' % len(mans))
    w('boots              %d' % len(boots))
    w('```')
    w('')

    if verdict in POSITIVE:
        head, body = POSITIVE[verdict]
    elif verdict == NEGATIVE:
        head = ('R1 was NOT OBSERVED on the tested configuration.')
        body = ('This is NOT_OBSERVED. It is not R1_DISPROVEN, and it does '
                'not generalise past what is listed under Scope below.')
    else:
        head, body = OTHER[verdict]

    w('## Reading')
    w('')
    w('**%s**' % head)
    w('')
    w(body)
    w('')

    w('## Denominator')
    w('')
    w('Two denominators exist and are never added together.')
    w('')
    w('```text')
    w('host attempts, valid      %d' % b_valid)
    w('host attempts, invalid    %d' % b_invalid)
    if reasons:
        for k in sorted(reasons):
            w('    %-22s %d' % (k, reasons[k]))
    w('unit                      host_attempts   (harness-issued triggers)')
    w('')
    if kernel_denom is not None:
        w('observer candidates       %s' % kernel_denom)
        w('unit                      %s'
          % g.get('denominator_unit', 'endpoint_stop_opportunities'))
        w('                          one SETUP can stop several endpoints,')
        w('                          so this is not a count of attempts')
    else:
        w('observer candidates       not reported by the gate')
    w('```')
    w('')

    if verdict == NEGATIVE:
        # A null result is only a null result if the instrument was alive.
        # The raw restore leaves the host's endpoint state untouched
        # (message.c:1819 is never reached), so an endpoint that stopped
        # moving payload would produce attempts that look exactly like
        # attempts that found nothing. The re-arm pre-flight is what
        # separates those two, and a negative may not be read without it.
        blind = [m['session']['session_id'] for _, m, _ in mans
                 if not m['preflight']['rearm']['discriminating']]
        w('The instrument was shown to survive the restore: every session '
          'below carries a two-arm re-arm pre-flight measuring payload '
          'progress, not submission, and the campaign refuses to start '
          'without a usable verdict from it.')
        w('')
        if blind:
            w('In %d of %d session(s) (%s) the pre-flight passed in BOTH '
              'arms. That is REARM_NO_RESET_NEEDED: this host controller '
              'showed no toggle desync, so the endpoint was demonstrably '
              'alive, but those sessions carry no evidence about the reset '
              'itself and none is claimed for it.'
              % (len(blind), len(mans), ', '.join(blind)))
            w('')
        w('The absence is quoted against **B = %d valid host attempts** '
          'across %d boot(s). Expressed as a probability, that is %s.'
          % (b_valid, len(boots), rule_of_three(b_valid)))
        w('')
        w('That figure is for orientation only. It is not a campaign result, '
          'and it must not be reported without the sentence that follows it '
          'here.')
        w('')

    w('## Scope -- what was tested')
    w('')
    w('```text')
    for path, m, _ in mans:
        s = m['session']
        w('session %-10s boot %-14s %s .. %s'
          % (s['session_id'], s['boot_id'][:12], s['started_utc'],
             s['ended_utc']))
        w('    target   %s  udc %s  gadget %s'
          % (s['target']['kernel_release'], s['target']['udc'],
             s['target']['gadget_config']))
        pf = m['preflight']
        w('    caps     g_dma=%d g_dma_desc=%d  (read from the dump header)'
          % (pf['caps']['g_dma'], pf['caps']['g_dma_desc']))
        w('    sens     %d issued / %d observed -> %s'
          % (pf['sensitivity']['triggers_issued'],
             pf['sensitivity']['sync_owner_candidates_observed'],
             pf['sensitivity']['verdict']))
        ra = pf['rearm']
        w('    rearm    control %d/%d, %s %d/%d -> %s%s'
          % (ra['arms'][0]['progress_ok'], ra['cycles'],
             ra['arms'][1]['method'], ra['arms'][1]['progress_ok'],
             ra['cycles'], ra['verdict'],
             '' if ra['discriminating'] else '  (not discriminating)'))
    w('```')
    w('')
    w('Buffer DMA only. Descriptor DMA is outside the frozen predicate and '
      'nothing here speaks to it. One trigger branch, one board, one kernel '
      'build.')
    w('')

    w('## What remains unknown')
    w('')
    w('These are carried forward explicitly. None of them is settled by this '
      'verdict, and none disappears by not being mentioned.')
    w('')
    w('```text')
    if verdict in POSITIVE:
        w('Q          UNKNOWN     an R1 positive does not bound it')
        w('U          NOT OBSERVED AT RUNTIME')
        w('             the record classifies what unmap WOULD do; it is not')
        w('             an observation that DMA followed one')
    else:
        w('Q          UNKNOWN')
        w('U          NOT OBSERVED')
    if any(not m['preflight']['rearm']['discriminating'] for _, m, _ in mans):
        w('rearm      NOT DISCRIMINATED')
        w('             both arms passed on this host controller, so whether')
        w('             USBDEVFS_RESETEP is load-bearing here is unsettled;')
        w('             it stays enabled as a precaution only')
    w('D_issue    UNKNOWN     needs paired timestamps from both sides')
    w('D_commit   UNKNOWN     needs an isolated, IOMMU-free target')
    w('R2         NOT STARTED  requires R1 first, and a translating IOMMU;')
    w('                        this board has none')
    w('P3         NOT BUILT    not required by base_r1_predicate(), which')
    w('                        contains no trigger term; blocking only for')
    w('                        class requests such as Printer SOFT_RESET')
    w('```')
    w('')

    w('## Epoch discipline')
    w('')
    w('```text')
    for k, v in sorted(mans[0][1]['epoch']['artifacts'].items()):
        w('%-20s %s' % (k, v))
    w('```')
    w('')
    w('A change to any of these is a new epoch. Negatives accumulated under '
      'the old one are demolished and recounted; a positive produced by a '
      'modified tool does not close R1 until it is reproduced under the '
      'epoch in force.')
    w('')

    w('## Evidence')
    w('')
    w('```text')
    for path, m, _ in mans:
        w('manifest   %s' % path)
        for k in ('dump', 'usbmon', 'holder_event_log', 'harness_log'):
            art = m['artifacts'][k]
            w('  %-10s %s  %s' % (k, art['sha256'][:16] + '...', art['path']))
    w('gate       %s' % a.gate)
    w('```')
    w('')
    w('*TEST-ONLY. Generated from the manifests and the gate output above; '
      'no figure in this document was entered by hand.*')

    text = '\n'.join(L) + '\n'
    if a.out:
        Path(a.out).write_text(text)
        print('wrote %s  (%s, B_valid=%d)' % (a.out, verdict, b_valid))
    else:
        sys.stdout.write(text)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
