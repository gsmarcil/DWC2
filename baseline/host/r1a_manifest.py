#!/usr/bin/env python3
"""R1A session manifest v1 -- schema and fail-closed validator.

P4 answers "was a timeout observed", and needs a denominator to say anything
when the answer is no. The kernel's candidate_* counters are endpoint-stop
opportunities, not host attempts, so the attempt denominator has to come from
the harness. This is the file that carries it, and the rules that stop it from
being taken on trust.

Three things are recomputed here rather than believed:

  * B_valid is counted from the attempt list, not read from the declared field.
    A manifest that claims a larger denominator than its own attempts support
    is rejected, because that is exactly the direction that inflates a negative
    result.
  * sensitivity is derived from the pairing counts, not from a verdict string.
    A manifest may not simply assert SENSITIVE.
  * an attempt is valid only if the harness recorded a machine check that the
    Bulk OUT transfer was outstanding at the instant the trigger went out.
    "I armed it first" is not a check.
  * the re-arm verdict is derived from the two arms of the pre-flight, and each
    arm's progress count is itself recomputed from the per-cycle bytes and
    status. A manifest may not assert that the endpoint came back usable.

Everything unknown is invalid. There is no default that lets a run count.

  usage: r1a_manifest.py MANIFEST.json [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MANIFEST_VERSION = 2
SHA256 = re.compile(r'^[0-9a-f]{64}$')
ISO = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$')

MODES = ('cfg0', 'cfgn', 'interface-sync', 'delayed-disable', 'delayed-dequeue')

# The observer counter each branch uses as its denominator. Mirrors MODES in
# r1_gate_v9.py; a manifest that took differences from a different field than
# the gate will read is not describing the same experiment.
MODE_FIELD = {
    'cfg0': 'candidate_cfg0_seen',
    'cfgn': 'candidate_cfgn_seen',
    'interface-sync': 'candidate_intf_seen',
    'delayed-disable': 'candidate_delayed_disable_seen',
    'delayed-dequeue': 'candidate_delayed_dequeue_seen',
}
DELAYED_MODES = ('delayed-disable', 'delayed-dequeue')
SETUP_FIELD = {
    'cfg0': 'setup_cfg0_seen',
    'cfgn': 'setup_cfgn_seen',
    'interface-sync': 'setup_intf_seen',
}

# Artifacts whose hash pins the epoch. Changing any one of them is a new epoch,
# which invalidates accumulated negatives (see EPOCH RULE in the schema doc).
EPOCH_ARTIFACTS = (
    'image',
    'observer_patch',
    'dwc2_r1_v9',
    'r1_gate_v9',          # byte-identical frozen v9 engine imported by v9.1
    'r1_gate_v9_1',        # evidence-binding wrapper
    'harness',
    'manifest_validator',
    'usbmon_verifier',
    'holder_merger',
    'verdict_generator',
)

# An attempt is only usable if the harness proved the transfer was still
# outstanding. These are the methods that constitute proof; anything else is
# rejected rather than silently accepted.
OUTSTANDING_METHODS = (
    'aio_inflight',       # io_getevents showed the read not yet reaped
    'urb_status_pending', # host-side URB still queued at trigger time
)

# --------------------------------------------------------------- re-arm
# The raw restore in the harness bypasses usb_set_configuration(), so usbcore
# never runs usb_enable_interface(dev, intf, true) (message.c:1819) and never
# resets the host's endpoint state, while the gadget resets itself to DATA0
# (gadget.c:5164). Whether that mismatch actually stops traffic depends on the
# host controller -- usb_hcd_reset_endpoint() (hcd.c:1990) defers to
# hcd->driver->endpoint_reset where one exists -- so it is measured, per host,
# in two arms, and the campaign does not start without a usable answer.
REARM_METHODS = ('none', 'resetep', 'clear_halt')

# Only these two let a campaign proceed. REARM_NO_RESET_NEEDED is an honest
# non-result: both arms worked, so the session carries no evidence about the
# reset and must not cite any.
REARM_ADMITS_CAMPAIGN = ('REARM_RESET_REQUIRED', 'REARM_NO_RESET_NEEDED')


def derive_rearm(performed, baseline_progress, cycles, none_ok, reset_ok):
    """The verdict rule, total by construction.

    Mirrors rearm_verdict() in r1a_host.c line for line. Divergence between
    the two would be a silent way for a session to be accepted here that the
    harness refused to run, so both are exercised against the same table in
    manifest_selftest.py.
    """
    if not performed:
        return 'REARM_NOT_TESTED', False
    if not baseline_progress:
        return 'REARM_BASELINE_FAILED', False
    if cycles < 3:
        return 'REARM_INDETERMINATE', False
    if reset_ok == cycles:
        if none_ok == 0:
            return 'REARM_RESET_REQUIRED', True
        if none_ok == cycles:
            return 'REARM_NO_RESET_NEEDED', False
        return 'REARM_INDETERMINATE', False
    if none_ok == cycles:
        return 'REARM_RESET_HARMFUL', False
    return 'REARM_BROKEN', False


def _rearm_progress(c, probe_len):
    """Recompute one cycle's REARM_DATA_PROGRESS from its primitives.

    Payload progress, not submission: a submit succeeds against a stalled
    toggle exactly as it does against a working one.
    """
    return (c.get('reaped') is True
            and c.get('first_bulk_completion_status') == 0
            and c.get('bytes_after_rearm') == probe_len)


# --------------------------------------------------- the measured denominator
# The observer's counters are cumulative, so a single read at the end contains
# the sensitivity burst and the re-arm pre-flight -- and in cfgn mode one
# classified SETUP per restore, because dwc2_r1_classify_setup() treats
# SET_CONFIGURATION with a non-zero wValue as TRIG_SET_CONFIG_NONZERO, which is
# exactly that branch's denominator field. Only differences between
# authenticated snapshots are accepted, and the difference has to agree with a
# measured candidates-per-attempt.
WINDOW_CODES = (
    'OK', 'NO_SNAPSHOTS', 'SNAPSHOT_PARSE', 'TARGET_CHANGED', 'CAPS_CHANGED',
    'OBSERVER_RESET', 'RECORDS_LOST', 'NOT_ATOMIC', 'COUNTER_BACKWARDS',
    'NO_SENS_ATTEMPT', 'SENS_INVALID', 'K_NOT_INTEGRAL', 'K_ZERO',
    'NO_VALID_ATTEMPT', 'RELATION_BROKEN',
)

CAP_DMA = 1 << 0
CAP_DDMA = 1 << 1


def derive_window(snaps, field, sens_issued, sens_attempted,
                  b_valid, b_invalid):
    """Recompute the denominator verdict. Mirrors kwindow_derive() in
    r1a_host.c; both are diffed row by row over an enumerated grid by
    rule_crosscheck.py, because a reworded copy that drifts would accept a
    session the harness itself refused to run.

    Returns (code, k, delta_sens, delta_camp, expected).
    """
    z = (0, 0, 0, 0)
    if len(snaps) != 3:
        return ('NO_SNAPSHOTS',) + z
    a, b, c = snaps
    if not all(x.get('ok') is True for x in snaps):
        return ('SNAPSHOT_PARSE',) + z
    if len({tuple(x.get('target') or ()) for x in snaps}) != 1:
        return ('TARGET_CHANGED',) + z
    if len({x.get('caps_flags') for x in snaps}) != 1:
        return ('CAPS_CHANGED',) + z
    if len({x.get('reset_generation') for x in snaps}) != 1:
        return ('OBSERVER_RESET',) + z
    if any(x.get('lost') for x in snaps):
        return ('RECORDS_LOST',) + z
    if any(x.get('snapshot_atomic') != 1 for x in snaps):
        return ('NOT_ATOMIC',) + z
    fa, fb, fc = (x.get('field_value') for x in snaps)
    if not all(isinstance(v, int) for v in (fa, fb, fc)):
        return ('SNAPSHOT_PARSE',) + z
    if fb < fa or fc < fb:
        return ('COUNTER_BACKWARDS',) + z

    d_sens, d_camp = fb - fa, fc - fb
    if sens_issued == 0:
        return ('NO_SENS_ATTEMPT', 0, d_sens, d_camp, 0)
    if sens_attempted != sens_issued:
        return ('SENS_INVALID', 0, d_sens, d_camp, 0)
    if d_sens % sens_issued:
        return ('K_NOT_INTEGRAL', 0, d_sens, d_camp, 0)
    k = d_sens // sens_issued
    if k < 1:
        return ('K_ZERO', 0, d_sens, d_camp, 0)
    # B = 0 before the relation, and not as a formality: 0 == k x 0 is true
    # and means nothing. A negative quoted against an empty denominator is
    # the failure this file exists to prevent.
    if b_valid == 0:
        return ('NO_VALID_ATTEMPT', k, d_sens, d_camp, 0)
    expected = k * b_valid
    if d_camp != expected:
        return ('RELATION_BROKEN', k, d_sens, d_camp, expected)
    return ('OK', k, d_sens, d_camp, expected)


VALID_INVALID_REASONS = (
    'not_checked', 'not_outstanding', 'submit_failed', 'in_excluded_window',
    'trigger_failed', 'device_gone', 'operator_aborted',
)


def _hash_field(errs, obj, key, label=None):
    label = label or key
    if not isinstance(obj, dict) or key not in obj:
        errs.append('missing %s' % label)
        return
    v = obj[key]
    if not isinstance(v, str) or not SHA256.match(v):
        errs.append('%s is not a sha256' % label)


def _ts(errs, v, what):
    if not isinstance(v, str) or not ISO.match(v):
        errs.append('%s is not an ISO-8601 Z timestamp' % what)
        return None
    return v


def validate(m: dict) -> list[str]:
    """Return a list of reasons the manifest may not be used. Empty means usable."""
    e: list[str] = []

    if not isinstance(m, dict):
        return ['manifest is not an object']
    if m.get('manifest_version') != MANIFEST_VERSION:
        return ['manifest_version must be %d' % MANIFEST_VERSION]

    # ---------------------------------------------------------------- epoch
    ep = m.get('epoch')
    if not isinstance(ep, dict):
        e.append('missing epoch')
    else:
        if not isinstance(ep.get('epoch_id'), str) or not ep['epoch_id']:
            e.append('missing epoch.epoch_id')
        arts = ep.get('artifacts')
        if not isinstance(arts, dict):
            e.append('missing epoch.artifacts')
        else:
            for a in EPOCH_ARTIFACTS:
                _hash_field(e, arts, a, 'epoch.artifacts.%s' % a)
            unknown = set(arts) - set(EPOCH_ARTIFACTS)
            if unknown:
                e.append('unpinned artifacts in epoch: %s'
                         % ','.join(sorted(unknown)))

    # -------------------------------------------------------------- session
    s = m.get('session')
    if not isinstance(s, dict):
        e.append('missing session')
        s = {}
    mode = s.get('mode')
    if mode not in MODES:
        e.append('session.mode must be one of %s' % ','.join(MODES))
    for k in ('session_id', 'boot_id'):
        if not isinstance(s.get(k), str) or not s.get(k):
            e.append('missing session.%s' % k)
    t0 = _ts(e, s.get('started_utc'), 'session.started_utc')
    t1 = _ts(e, s.get('ended_utc'), 'session.ended_utc')
    if t0 and t1 and t1 < t0:
        e.append('session ends before it starts')
    for grp, keys in (('target', ('kernel_release', 'udc', 'gadget_config')),
                      ('host', ('kernel', 'usbmon_bus'))):
        g = s.get(grp)
        if not isinstance(g, dict):
            e.append('missing session.%s' % grp)
            continue
        for k in keys:
            if k not in g:
                e.append('missing session.%s.%s' % (grp, k))
    trig = s.get('trigger')
    if not isinstance(trig, dict):
        e.append('missing session.trigger')
    else:
        for k in ('bmRequestType','bRequest','wValue','wIndex','wLength'):
            if not isinstance(trig.get(k), int):
                e.append('session.trigger.%s must be an integer' % k)
    if not isinstance(s.get('restore_cfg'), int):
        e.append('session.restore_cfg must be an integer')

    # ------------------------------------------------------------ preflight
    pf = m.get('preflight')
    if not isinstance(pf, dict):
        e.append('missing preflight')
        pf = {}

    caps = pf.get('caps', {})
    if caps.get('g_dma') != 1:
        e.append('preflight.caps.g_dma must be 1 (buffer DMA)')
    if caps.get('g_dma_desc') != 0:
        e.append('preflight.caps.g_dma_desc must be 0 (DDMA is out of scope)')
    if caps.get('source') != 'dump_header':
        e.append('preflight.caps.source must be dump_header: a platform quirk '
                 'can override a cmdline value, so the running kernel is the '
                 'only authority')
    # ... and "dump_header" has to name WHICH dump, or it is still a label.
    _hash_field(e, caps, 'from_sha256', 'preflight.caps.from_sha256')

    abi = pf.get('abi', {})
    if (abi.get('version'), abi.get('header_size'), abi.get('record_size')) \
            != (9, 112, 80):
        e.append('preflight.abi must be version 9 / header 112 / record 80')
    if pf.get('snapshot_atomic') != 1:
        e.append('preflight.snapshot_atomic must be 1')
    if pf.get('lost') != 0:
        e.append('preflight.lost must be 0; a session that dropped records '
                 'cannot support a negative result')

    # ---------------------------------------------------- sensitivity, derived
    sens = pf.get('sensitivity', {})
    if sens.get('protocol') != 'paired_positive_control':
        e.append('preflight.sensitivity.protocol must be '
                 'paired_positive_control')
    issued = sens.get('triggers_issued')
    seen = sens.get('sync_owner_candidates_observed')
    if not isinstance(issued, int) or issued < 1:
        e.append('sensitivity.triggers_issued must be a positive integer')
    if sens.get('source') != 'S0_S1_dump_headers':
        e.append('sensitivity.source must be S0_S1_dump_headers; operator-provided counts are not evidence')
    if not isinstance(seen, int) or seen < 0:
        e.append('sensitivity.sync_owner_candidates_observed must be an integer')

    for w in sens.get('excluded_windows', []) or []:
        if not isinstance(w, dict) or w.get('reason') not in (
                'enumeration', 'port_reset', 'operator'):
            e.append('excluded window has no recognised reason')
            continue
        _ts(e, w.get('t0'), 'excluded window t0')
        _ts(e, w.get('t1'), 'excluded window t1')

    # ---------------------------------------------------- re-arm, derived
    ra = pf.get('rearm')
    if not isinstance(ra, dict):
        e.append('missing preflight.rearm: a session whose restore path was '
                 'never shown to hand back a working endpoint cannot '
                 'distinguish a null result from a dead instrument')
    else:
        if ra.get('protocol') != 'two_arm_payload_progress':
            e.append('preflight.rearm.protocol must be '
                     'two_arm_payload_progress')

        probe_len = ra.get('probe_len')
        if not isinstance(probe_len, int) or probe_len < 1:
            e.append('preflight.rearm.probe_len must be a positive integer')
            probe_len = None
        if not isinstance(ra.get('timeout_ms'), int) \
                or ra.get('timeout_ms', 0) < 50:
            e.append('preflight.rearm.timeout_ms must be at least 50')

        performed = ra.get('performed')
        if not isinstance(performed, bool):
            e.append('preflight.rearm.performed must be a boolean')
            performed = False

        base = ra.get('baseline')
        base_ok = False
        if not isinstance(base, dict):
            e.append('missing preflight.rearm.baseline')
        else:
            _ts(e, base.get('t0'), 'rearm.baseline.t0')
            _ts(e, base.get('t1'), 'rearm.baseline.t1')
            if probe_len is not None:
                base_ok = _rearm_progress(base, probe_len)
                if base.get('REARM_DATA_PROGRESS') is not base_ok:
                    e.append('rearm.baseline.REARM_DATA_PROGRESS is %r but '
                             'its own status/bytes derive %r; progress is '
                             'recomputed, never declared'
                             % (base.get('REARM_DATA_PROGRESS'), base_ok))

        arms = ra.get('arms')
        arm_ok = [0, 0]
        arm_len = [0, 0]
        if not isinstance(arms, list) or len(arms) != 2:
            e.append('preflight.rearm.arms must be exactly two: a control arm '
                     'and a treatment arm. One arm cannot discriminate')
            arms = []
        else:
            if arms[0].get('method') != 'none':
                e.append('rearm.arms[0].method must be none (the control arm)')
            if arms[1].get('method') not in ('resetep', 'clear_halt'):
                e.append('rearm.arms[1].method must be resetep or clear_halt; '
                         'two identical arms cannot discriminate by '
                         'construction')
            if ra.get('reset_method_in_use') != arms[1].get('method'):
                e.append('rearm.reset_method_in_use is %r but the treatment '
                         'arm tested %r; the campaign must run the method the '
                         'pre-flight validated'
                         % (ra.get('reset_method_in_use'),
                            arms[1].get('method')))
            for ai, arm in enumerate(arms):
                tagp = 'rearm.arms[%d]' % ai
                cyc = arm.get('cycles')
                if not isinstance(cyc, list):
                    e.append('%s.cycles must be a list' % tagp)
                    continue
                arm_len[ai] = len(cyc)
                ok = 0
                reenum = 0
                for ci, c in enumerate(cyc):
                    if not isinstance(c, dict):
                        e.append('%s.cycles[%d] is not an object' % (tagp, ci))
                        continue
                    _ts(e, c.get('t0'), '%s.cycles[%d].t0' % (tagp, ci))
                    _ts(e, c.get('t1'), '%s.cycles[%d].t1' % (tagp, ci))
                    if c.get('reenum') is True:
                        reenum += 1
                    if probe_len is None:
                        continue
                    p = _rearm_progress(c, probe_len)
                    if c.get('REARM_DATA_PROGRESS') is not p:
                        e.append('%s.cycles[%d].REARM_DATA_PROGRESS is %r but '
                                 'status=%r bytes=%r derive %r'
                                 % (tagp, ci, c.get('REARM_DATA_PROGRESS'),
                                    c.get('first_bulk_completion_status'),
                                    c.get('bytes_after_rearm'), p))
                    if p:
                        ok += 1
                arm_ok[ai] = ok
                if arm.get('progress_ok') != ok:
                    e.append('%s.progress_ok is %r but %d of its cycles '
                             'actually made payload progress'
                             % (tagp, arm.get('progress_ok'), ok))
                if arm.get('reenum') != reenum:
                    e.append('%s.reenum is %r but %d cycles re-enumerated'
                             % (tagp, arm.get('reenum'), reenum))

        cycles = ra.get('cycles')
        if not isinstance(cycles, int) or cycles < 0:
            e.append('preflight.rearm.cycles must be a non-negative integer')
            cycles = 0
        elif arms and cycles != min(arm_len):
            e.append('preflight.rearm.cycles is %d but the arms recorded %d '
                     'and %d cycles; the comparable length is the shorter one'
                     % (cycles, arm_len[0], arm_len[1]))

        verdict, disc = derive_rearm(performed, base_ok, cycles,
                                     arm_ok[0], arm_ok[1])
        if ra.get('verdict') != verdict:
            e.append('rearm.verdict is %r but the arms derive %r '
                     '(cycles=%d none=%d treatment=%d baseline=%r); the '
                     'verdict is computed, not declared'
                     % (ra.get('verdict'), verdict, cycles,
                        arm_ok[0], arm_ok[1], base_ok))
        if ra.get('discriminating') is not disc:
            e.append('rearm.discriminating is %r but the arms derive %r'
                     % (ra.get('discriminating'), disc))
        if verdict not in REARM_ADMITS_CAMPAIGN:
            e.append('re-arm verdict %s does not admit a campaign. The '
                     'designated fallback is one destructive attempt per '
                     'fresh enumeration epoch, with B counted in epochs '
                     'rather than attempts' % verdict)

    # -------------------------------------------- denominator window, derived
    kwin = m.get('kernel_window')
    kwin_snaps: list = []
    kwin_sens_att = -1
    s2_sha = None
    if not isinstance(kwin, dict):
        e.append('missing kernel_window: without snapshots around the '
                 'campaign the denominator is a cumulative counter that also '
                 'contains the sensitivity burst and the re-arm pre-flight')
        kwin = {}
    else:
        if kwin.get('unit') != 'endpoint_stop_opportunities':
            e.append('kernel_window.unit must be endpoint_stop_opportunities')
        if mode in MODE_FIELD and kwin.get('field') != MODE_FIELD[mode]:
            e.append('kernel_window.field is %r but mode %r is gated on %r'
                     % (kwin.get('field'), mode, MODE_FIELD.get(mode)))

        snaps = kwin.get('snapshots')
        if not isinstance(snaps, list) or len(snaps) != 3:
            e.append('kernel_window.snapshots must be exactly three: before '
                     'the sensitivity burst, before the campaign, after it')
            snaps = []
        else:
            want = (('S0', 'after_rearm_before_sensitivity'),
                    ('S1', 'after_sensitivity_before_campaign'),
                    ('S2', 'after_campaign'))
            times = []
            for i, (sn, (lbl, when)) in enumerate(zip(snaps, want)):
                if not isinstance(sn, dict):
                    e.append('kernel_window.snapshots[%d] is not an object' % i)
                    continue
                if sn.get('label') != lbl or sn.get('when') != when:
                    e.append('kernel_window.snapshots[%d] is %r/%r, expected '
                             '%r/%r; the window boundaries are fixed'
                             % (i, sn.get('label'), sn.get('when'), lbl, when))
                _hash_field(e, sn, 'sha256',
                            'kernel_window.snapshots[%d].sha256' % i)
                t = _ts(e, sn.get('utc'),
                        'kernel_window.snapshots[%d].utc' % i)
                if t:
                    times.append(t)
            if len(times) == 3 and not (times[0] <= times[1] <= times[2]):
                e.append('the three snapshots are not in order')
            if snaps and isinstance(snaps[2], dict):
                s2_sha = snaps[2].get('sha256')

        # Sensitivity is derived from the same authenticated S0/S1 headers.
        if len(snaps) == 3 and all(isinstance(x, dict) for x in snaps):
            s0, s1, s2 = snaps
            cs0, cs1 = s0.get('causal_sync_count'), s1.get('causal_sync_count')
            setup0, setup1 = s0.get('setup_value'), s1.get('setup_value')
            causal_delta = cs1 - cs0 if isinstance(cs0,int) and isinstance(cs1,int) and cs1 >= cs0 else None
            setup_delta = setup1 - setup0 if isinstance(setup0,int) and isinstance(setup1,int) and setup1 >= setup0 else None
            if mode in SETUP_FIELD and s0.get('setup_field') != SETUP_FIELD[mode]:
                e.append('S0/S1 setup_field is not the setup counter for mode %r' % mode)
            if mode in SETUP_FIELD and s1.get('setup_field') != SETUP_FIELD[mode]:
                e.append('S1 setup_field is not the setup counter for mode %r' % mode)
            if sens.get('sync_owner_candidates_observed') != causal_delta:
                e.append('sensitivity.sync_owner_candidates_observed is %r but S0/S1 causal_sync derive %r' % (sens.get('sync_owner_candidates_observed'), causal_delta))
            if sens.get('setup_triggers_observed') != setup_delta:
                e.append('sensitivity.setup_triggers_observed is %r but S0/S1 setup counter derives %r' % (sens.get('setup_triggers_observed'), setup_delta))
            derived = 'SENSITIVE' if (isinstance(issued,int) and issued >= 1 and causal_delta == issued and setup_delta == issued) else 'INSENSITIVE'
            if sens.get('verdict') != derived:
                e.append('sensitivity.verdict is %r but S0/S1 headers derive %r' % (sens.get('verdict'), derived))
            if derived != 'SENSITIVE':
                e.append('sensitivity is not SENSITIVE: issued=%r causal_sync_delta=%r setup_delta=%r' % (issued, causal_delta, setup_delta))
            rs = kwin.get('record_slice') or {}
            start, end = s1.get('count'), s2.get('count')
            if rs.get('start') != start or rs.get('end') != end:
                e.append('kernel_window.record_slice must equal S1.count..S2.count')
            if not isinstance(start,int) or not isinstance(end,int) or start > end:
                e.append('invalid campaign record slice bounds')

        sens_att = (kwin.get('k') or {}).get('attempts')
        if not isinstance(sens_att, int) or sens_att < 0:
            e.append('kernel_window.k.attempts must be an integer')
            sens_att = -1
        elif isinstance(issued, int) and sens_att < issued:
            e.append('kernel_window.k.attempts (%d) is below '
                     'sensitivity.triggers_issued (%d): the window cannot '
                     'hold fewer attempts than it counted'
                     % (sens_att, issued))

        kwin_snaps, kwin_sens_att = snaps, sens_att

    # -------------------------------------------------------------- attempts
    attempts = m.get('attempts')
    if not isinstance(attempts, list) or not attempts:
        e.append('attempts must be a non-empty list')
        attempts = []

    seen_n = set()
    counted_valid = 0
    counted_invalid = 0
    reason_tally: dict[str, int] = {}

    for i, a in enumerate(attempts):
        tag = 'attempt[%d]' % i
        if not isinstance(a, dict):
            e.append('%s is not an object' % tag)
            continue
        n = a.get('n')
        if not isinstance(n, int) or n < 1:
            e.append('%s.n must be a positive integer' % tag)
        elif n in seen_n:
            e.append('%s.n=%d is duplicated' % (tag, n))
        else:
            seen_n.add(n)

        ta = _ts(e, a.get('t_arm_utc'), '%s.t_arm_utc' % tag)
        tt = _ts(e, a.get('t_trigger_utc'), '%s.t_trigger_utc' % tag)
        if ta and tt and tt < ta:
            e.append('%s triggers before it arms' % tag)

        out = a.get('outstanding')
        valid = a.get('valid')
        if not isinstance(valid, bool):
            e.append('%s.valid must be a boolean' % tag)
            valid = False

        # The validity predicate. An attempt counts only with a recorded
        # machine check, taken at trigger time, that the transfer had not
        # completed. Arming is not evidence.
        ok_outstanding = False
        if not isinstance(out, dict):
            e.append('%s.outstanding is missing' % tag)
        elif out.get('checked') is not True:
            pass                       # legitimately invalid, not an error
        elif out.get('method') not in OUTSTANDING_METHODS:
            e.append('%s.outstanding.method %r is not an accepted proof'
                     % (tag, out.get('method')))
        elif out.get('urb_completed') is not False:
            pass                       # completed before the trigger: invalid
        elif not isinstance(out.get('inflight_at_trigger'), int) \
                or out['inflight_at_trigger'] < 1:
            pass
        else:
            ok_outstanding = True

        # Did the control request actually reach the wire? An attempt that
        # fired and still did not qualify leaves candidates in an aggregate
        # counter that nothing can subtract, so it voids the batch rather
        # than shortening it by one.
        fired = a.get('trigger_attempted')
        if not isinstance(fired, bool):
            e.append('%s.trigger_attempted must be a boolean' % tag)
            fired = None
        elif fired and not valid:
            e.append('%s fired its trigger and is invalid (%r): the batch is '
                     'void, because the candidates it left cannot be removed '
                     'from the observer counter'
                     % (tag, a.get('invalid_reason')))
        elif valid and not fired:
            e.append('%s is marked valid but never issued a trigger' % tag)

        if valid and not ok_outstanding:
            e.append('%s is marked valid but its outstanding check does not '
                     'support it' % tag)
        if not valid:
            r = a.get('invalid_reason')
            if r not in VALID_INVALID_REASONS:
                e.append('%s is invalid with unrecognised reason %r'
                         % (tag, r))
            else:
                reason_tally[r] = reason_tally.get(r, 0) + 1
            counted_invalid += 1
        else:
            counted_valid += 1

    # ----------------------------------------------- denominator, recomputed
    den = m.get('denominator')
    if not isinstance(den, dict):
        e.append('missing denominator')
    else:
        if den.get('unit') != 'host_attempts':
            e.append('denominator.unit must be host_attempts; the kernel '
                     'counters are endpoint_stop_opportunities and are not '
                     'interchangeable with this')
        if den.get('B_valid') != counted_valid:
            e.append('denominator.B_valid is %r but %d attempts are actually '
                     'valid; B is recomputed, never trusted'
                     % (den.get('B_valid'), counted_valid))
        if den.get('B_invalid') != counted_invalid:
            e.append('denominator.B_invalid is %r but %d attempts are invalid'
                     % (den.get('B_invalid'), counted_invalid))
        if den.get('invalid_reasons') != reason_tally:
            e.append('denominator.invalid_reasons does not match the attempts')
        if den.get('batch_void') is not False:
            e.append('denominator.batch_void is %r: a void batch carries no '
                     'denominator' % den.get('batch_void'))

        code, k, d_sens, d_camp, expected = derive_window(
            kwin_snaps, kwin.get('field'),
            issued if isinstance(issued, int) else 0,
            kwin_sens_att, counted_valid, counted_invalid)

        if kwin.get('code') != code:
            e.append('kernel_window.code is %r but the snapshots derive %r; '
                     'the verdict is computed, not declared'
                     % (kwin.get('code'), code))
        if code != 'OK':
            e.append('the denominator window is not usable (%s): '
                     'delta_sens=%d delta_campaign=%d k=%d expected=%d '
                     'B_valid=%d' % (code, d_sens, d_camp, k, expected,
                                     counted_valid))
        kk = kwin.get('k') or {}
        if kk.get('k') != k or kk.get('delta') != d_sens:
            e.append('kernel_window.k says k=%r delta=%r but the snapshots '
                     'give k=%d delta=%d' % (kk.get('k'), kk.get('delta'),
                                             k, d_sens))
        camp = kwin.get('campaign') or {}
        if camp.get('delta') != d_camp or camp.get('expected') != expected:
            e.append('kernel_window.campaign says delta=%r expected=%r but '
                     'the snapshots give delta=%d expected=%d'
                     % (camp.get('delta'), camp.get('expected'),
                        d_camp, expected))
        if camp.get('relation_ok') is not (code == 'OK'):
            e.append('kernel_window.campaign.relation_ok is %r but the '
                     'arithmetic derives %r'
                     % (camp.get('relation_ok'), code == 'OK'))
        if den.get('kernel_delta') != d_camp or den.get('k') != k:
            e.append('denominator.kernel_delta/k (%r/%r) disagree with the '
                     'snapshots (%d/%d)' % (den.get('kernel_delta'),
                                            den.get('k'), d_camp, k))

    # ------------------------------------------------ wire witness, derived
    #
    # The harness reads its own inflight count, then issues the ioctl. A
    # transfer can complete in between, and the attempt is then recorded as
    # valid with nothing outstanding on the wire. The harness cannot detect
    # that, because the harness is the thing that was wrong, so a witness it
    # does not control is required before any attempt counts.
    wire = m.get('wire')
    if not isinstance(wire, dict):
        e.append('missing wire: without a usbmon re-derivation, '
                 'inflight_at_trigger is the harness marking its own work')
    else:
        if wire.get('protocol') != 'usbmon_post_hoc':
            e.append('wire.protocol must be usbmon_post_hoc')
        rows = wire.get('attempts')
        if not isinstance(rows, list):
            e.append('wire.attempts must be a list')
            rows = []
        agree = qual = 0
        by_n = {}
        for i, r in enumerate(rows):
            if not isinstance(r, dict):
                e.append('wire.attempts[%d] is not an object' % i)
                continue
            n_out = r.get('wire_inflight_at_control')
            internal = r.get('internal_inflight_at_trigger')
            a_ok = isinstance(n_out, int) and n_out == internal
            q_ok = isinstance(n_out, int) and n_out >= 1
            if r.get('agree') is not a_ok:
                e.append('wire.attempts[%d].agree is %r but wire=%r '
                         'harness=%r derive %r'
                         % (i, r.get('agree'), n_out, internal, a_ok))
            if r.get('qualifies') is not q_ok:
                e.append('wire.attempts[%d].qualifies is %r but wire=%r '
                         'derives %r' % (i, r.get('qualifies'), n_out, q_ok))
            agree += a_ok
            qual += q_ok
            by_n[r.get('n')] = (a_ok, q_ok)
        if wire.get('agree_count') != agree:
            e.append('wire.agree_count is %r but %d rows actually agree'
                     % (wire.get('agree_count'), agree))
        if wire.get('qualify_count') != qual:
            e.append('wire.qualify_count is %r but %d rows actually qualify'
                     % (wire.get('qualify_count'), qual))
        if wire.get('extra_controls') != 0:
            e.append('wire.extra_controls must be 0; extra matching campaign controls are not attributable')
        if wire.get('verdict') != 'WIRE_CONFIRMED':
            e.append('wire.verdict is %r: the capture did not confirm that a '
                     'transfer was outstanding when the trigger went out'
                     % wire.get('verdict'))
        # Every attempt the harness counted has to appear in the witness.
        for a in attempts:
            if a.get('valid') and a.get('n') not in by_n:
                e.append('attempt %r is valid but has no row in the wire '
                         'witness' % a.get('n'))
            elif a.get('valid') and not all(by_n[a['n']]):
                e.append('attempt %r is valid but the capture does not '
                         'support it' % a.get('n'))
        cap = (m.get('artifacts') or {}).get('usbmon') or {}
        if cap.get('scope') != 'campaign_only':
            e.append('artifacts.usbmon.scope must be campaign_only; preflight controls are not attributable campaign traffic')
        if wire.get('capture_sha256') != cap.get('sha256'):
            e.append('wire.capture_sha256 %r is not the capture the manifest '
                     'ships (%r)' % (wire.get('capture_sha256'),
                                     cap.get('sha256')))

    # ---------------------------------------------- holder witness, derived
    #
    # The wire witness shows a URB outstanding in the host controller driver.
    # That is not the claim: R1 is about a request still queued in the
    # function driver at teardown, and the two can differ. This is the
    # gadget's own count, paired by order rather than by clock.
    hold = m.get('holder')
    if not isinstance(hold, dict):
        e.append('missing holder: host-side outstanding does not establish '
                 'that the gadget still had a request queued')
    else:
        if hold.get('protocol') != 'device_teardown_depth':
            e.append('holder.protocol must be device_teardown_depth')
        if hold.get('pairing') != 'by_order_not_by_clock':
            e.append('holder.pairing must be by_order_not_by_clock: pairing '
                     'two machines on timestamps imports their clock skew '
                     'into the evidence')
        if hold.get('session_id') != s.get('session_id') or hold.get('boot_id') != s.get('boot_id'):
            e.append('holder session/boot identity does not match manifest session')
        hev = (m.get('artifacts') or {}).get('holder_event_log') or {}
        if hold.get('event_log_sha256') != hev.get('sha256'):
            e.append('holder.event_log_sha256 is not the holder event log the manifest ships')
        if hold.get('extra_teardowns') != 0:
            e.append('holder.extra_teardowns must be 0; extra campaign teardown traffic is not attributable')
        floor = hold.get('floor')
        if not isinstance(floor, int) or floor < 1:
            e.append('holder.floor must be at least 1; a floor of zero '
                     'asserts nothing')
            floor = None
        rows = hold.get('attempts')
        if not isinstance(rows, list):
            e.append('holder.attempts must be a list')
            rows = []
        meet = 0
        held = {}
        for i, r in enumerate(rows):
            if not isinstance(r, dict):
                e.append('holder.attempts[%d] is not an object' % i)
                continue
            p = r.get('pending_reads')
            ok = floor is not None and isinstance(p, int) and p >= floor
            if r.get('meets_floor') is not ok:
                e.append('holder.attempts[%d].meets_floor is %r but '
                         'pending_reads=%r against floor %r derives %r'
                         % (i, r.get('meets_floor'), p, floor, ok))
            meet += ok
            held[r.get('n')] = ok
        if hold.get('meets_floor_count') != meet:
            e.append('holder.meets_floor_count is %r but %d rows actually '
                     'meet the floor' % (hold.get('meets_floor_count'), meet))
        if hold.get('verdict') != 'HOLDER_CONFIRMED':
            e.append('holder.verdict is %r: the gadget was not shown to have '
                     'a request queued at teardown' % hold.get('verdict'))
        for a in attempts:
            if a.get('valid') and not held.get(a.get('n')):
                e.append('attempt %r is valid but the gadget-side depth does '
                         'not support it' % a.get('n'))

    # -------------------------------------------------------------- artifacts
    art = m.get('artifacts')
    if not isinstance(art, dict):
        e.append('missing artifacts')
    else:
        for k in ('dump', 'usbmon', 'harness_log', 'holder_event_log'):
            v = art.get(k)
            if not isinstance(v, dict):
                e.append('missing artifacts.%s' % k)
                continue
            if not isinstance(v.get('path'), str) or not v['path']:
                e.append('artifacts.%s.path missing' % k)
            _hash_field(e, v, 'sha256', 'artifacts.%s.sha256' % k)
        # The dump P4 will read has to be the same bytes the window closed on
        # and the same bytes the caps were taken from. Otherwise the session
        # describes one dump and ships another.
        dump = art.get('dump') or {}
        if s2_sha and dump.get('sha256') != s2_sha:
            e.append('artifacts.dump.sha256 %r is not the final snapshot %r: '
                     'the shipped trace is not the one the window closed on'
                     % (dump.get('sha256'), s2_sha))
        if caps.get('from_sha256') and dump.get('sha256') \
                and caps['from_sha256'] != dump.get('sha256'):
            e.append('preflight.caps came from %r but the shipped dump is %r'
                     % (caps['from_sha256'], dump.get('sha256')))

    # ------------------------------------------- delayed-branch extra gate
    if mode in DELAYED_MODES:
        oc = pf.get('overlap_count')
        if oc != 0:
            e.append('mode %s requires preflight.overlap_count == 0 (got %r): '
                     'the f_mass_storage worker can be signalled before '
                     'fsg_set_alt() returns delayed status, so a causal '
                     'dequeue can be recorded as OVERLAP' % (mode, oc))

    return e


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('manifest')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args()

    try:
        m = json.loads(Path(a.manifest).read_text())
    except (OSError, ValueError) as ex:
        print('MANIFEST UNREADABLE: %s' % ex, file=sys.stderr)
        return 2

    errs = validate(m)
    if a.json:
        print(json.dumps({'usable': not errs, 'errors': errs}, indent=2))
    else:
        for x in errs:
            print('  reject: %s' % x)
        print('MANIFEST: %s' % ('USABLE' if not errs
                                else '%d REASON(S) NOT TO USE' % len(errs)))
    return 0 if not errs else 1


if __name__ == '__main__':
    raise SystemExit(main())
