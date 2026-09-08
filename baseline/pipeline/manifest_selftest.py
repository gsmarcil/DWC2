#!/usr/bin/env python3
"""Discriminating tests for the R1A manifest validator.

Every rejection path is exercised deliberately. A validator that has only ever
seen a good manifest proves nothing: the whole point is that it refuses the
specific shapes that would inflate a negative result.
"""
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from r1a_manifest import validate

from fixtures import manifest, rearm_block, rearm_cycle, sha, PROBE

H = '%064x'


def good():
    """A clean, usable session. Two valid attempts and one that never fired,
    so the tests that need an invalid attempt have one to work with."""
    m = manifest('s001', sha('dump-one'), b_valid=2)
    m['attempts'].append({
        'n': 3, 't_arm_utc': '2026-09-07T10:05:10Z',
        't_trigger_utc': '2026-09-07T10:05:11Z',
        'outstanding': {'checked': True, 'method': 'aio_inflight',
                        'inflight_at_trigger': 0, 'urb_completed': True},
        'trigger_attempted': False, 'trigger_rc': 0,
        'valid': False, 'invalid_reason': 'not_outstanding'})
    m['denominator']['B_invalid'] = 1
    m['denominator']['invalid_reasons'] = {'not_outstanding': 1}
    return m


CASES = []


def case(name, want_ok, mutate=None, expect_substr=None):
    CASES.append((name, want_ok, mutate, expect_substr))


case('pristine manifest', True)

# --- denominator inflation, the failure mode that matters most
def _inflate(m): m['denominator']['B_valid'] += 1
case('B_valid inflated above real count', False, _inflate, 'recomputed')

def _valid_without_check(m):
    m['attempts'][-1]['valid'] = True
    m['attempts'][-1]['invalid_reason'] = None
    m['denominator'].update(B_valid=2, B_invalid=0, invalid_reasons={})
case('attempt marked valid though transfer had completed', False,
     _valid_without_check, 'outstanding check does not support it')

def _unchecked(m):
    m['attempts'][0]['outstanding'] = {'checked': False}
case('valid attempt with no outstanding check', False, _unchecked,
     'does not support it')

def _bad_method(m):
    m['attempts'][0]['outstanding']['method'] = 'i_armed_it_first'
case('outstanding proved by an unaccepted method', False, _bad_method,
     'not an accepted proof')

# --- sensitivity may not be asserted
def _assert_sensitive(m):
    m['preflight']['sensitivity'].update(triggers_issued=20,
                                         sync_owner_candidates_observed=17)
case('sensitivity declared but pairing does not match', False,
     _assert_sensitive, 'S0/S1 causal_sync derive')

def _zero_triggers(m):
    m['preflight']['sensitivity'].update(triggers_issued=0,
                                         sync_owner_candidates_observed=0,
                                         verdict='INSENSITIVE')
case('no positive control run at all', False, _zero_triggers, 'positive integer')

# --- target scope
def _ddma(m): m['preflight']['caps']['g_dma_desc'] = 1
case('DDMA target', False, _ddma, 'out of scope')

def _cmdline_caps(m): m['preflight']['caps']['source'] = 'kernel_cmdline'
case('caps taken from cmdline instead of the running kernel', False,
     _cmdline_caps, 'running kernel is the only authority')

def _lost(m): m['preflight']['lost'] = 3
case('session dropped records', False, _lost, 'cannot support a negative')

def _nonatomic(m): m['preflight']['snapshot_atomic'] = 0
case('non-atomic snapshot', False, _nonatomic, 'snapshot_atomic')

def _v8(m): m['preflight']['abi']['version'] = 8
case('ABI v8 dump', False, _v8, 'version 9')

# --- delayed branch
def _delayed_overlap(m):
    m['session']['mode'] = 'delayed-dequeue'
    m['kernel_window']['field'] = 'candidate_delayed_dequeue_seen'
    m['preflight']['overlap_count'] = 2
case('delayed mode with overlap_count != 0', False, _delayed_overlap,
     'recorded as OVERLAP')

def _delayed_clean(m):
    m['session']['mode'] = 'delayed-dequeue'
    m['kernel_window']['field'] = 'candidate_delayed_dequeue_seen'
case('delayed mode with overlap_count == 0', True, _delayed_clean)

# --- epoch pinning
def _missing_art(m): del m['epoch']['artifacts']['harness']
case('harness not pinned in the epoch', False, _missing_art,
     'epoch.artifacts.harness')

def _extra_art(m): m['epoch']['artifacts']['mystery_tool'] = H % 11
case('an unpinned extra artifact', False, _extra_art, 'unpinned artifacts')

def _bad_hash(m): m['epoch']['artifacts']['image'] = 'not-a-hash'
case('artifact hash is not a sha256', False, _bad_hash, 'not a sha256')

# --- bookkeeping integrity
def _dup_n(m): m['attempts'][1]['n'] = 1
case('duplicate attempt number', False, _dup_n, 'duplicated')

def _time_travel(m):
    m['attempts'][0]['t_trigger_utc'] = '2026-09-07T10:04:00Z'
case('trigger before arm', False, _time_travel, 'triggers before it arms')

def _no_attempts(m): m['attempts'] = []
case('no attempts at all', False, _no_attempts, 'non-empty')

def _wrong_unit(m): m['denominator']['unit'] = 'endpoint_stop_opportunities'
case('kernel counter unit used as the host denominator', False, _wrong_unit,
     'not interchangeable')

def _no_dump(m): del m['artifacts']['dump']
case('dump artifact missing', False, _no_dump, 'artifacts.dump')

# --- host endpoint re-arm: the instrument has to be shown to work
def _no_rearm(m): del m['preflight']['rearm']
case('no re-arm evidence at all', False, _no_rearm, 'missing preflight.rearm')

def _rearm_asserted(m):
    m['preflight']['rearm']['verdict'] = 'REARM_RESET_REQUIRED'
    m['preflight']['rearm']['arms'][1]['progress_ok'] = 4
    for c in m['preflight']['rearm']['arms'][1]['cycles']:
        c['REARM_DATA_PROGRESS'] = False
        c['reaped'] = False
        c['first_bulk_completion_status'] = -110
        c['bytes_after_rearm'] = 0
case('treatment arm asserts progress it did not make', False, _rearm_asserted,
     'actually made payload progress')

def _rearm_submitted_only(m):
    # The exact confusion the protocol exists to prevent: the URB went out
    # and nothing errored, but no payload moved.
    for c in m['preflight']['rearm']['arms'][1]['cycles']:
        c['reaped'] = True
        c['first_bulk_completion_status'] = 0
        c['bytes_after_rearm'] = 0
case('submitted but zero bytes counted as progress', False,
     _rearm_submitted_only, 'derive')

def _rearm_broken(m):
    m['preflight']['rearm'] = rearm_block(none_ok=0, reset_ok=1)
case('reset arm does not restore progress', False, _rearm_broken,
     'does not admit a campaign')

def _rearm_nondiscriminating(m):
    m['preflight']['rearm'] = rearm_block(none_ok=4, reset_ok=4)
case('both arms pass: allowed, but not discriminating', True,
     _rearm_nondiscriminating)

def _rearm_two_identical_arms(m):
    m['preflight']['rearm']['arms'][1]['method'] = 'none'
    m['preflight']['rearm']['reset_method_in_use'] = 'none'
case('treatment arm is a second control arm', False, _rearm_two_identical_arms,
     'cannot discriminate by construction')

def _rearm_method_mismatch(m):
    m['preflight']['rearm']['reset_method_in_use'] = 'clear_halt'
case('campaign runs a method the pre-flight did not test', False,
     _rearm_method_mismatch, 'must run the method the pre-flight validated')

def _rearm_baseline_dead(m):
    m['preflight']['rearm']['baseline'] = rearm_cycle(0, False)
    m['preflight']['rearm']['verdict'] = 'REARM_BASELINE_FAILED'
    m['preflight']['rearm']['discriminating'] = False
case('device side was not reading during the baseline', False,
     _rearm_baseline_dead, 'REARM_BASELINE_FAILED')

def _rearm_one_arm(m):
    m['preflight']['rearm']['arms'] = m['preflight']['rearm']['arms'][1:]
case('only the treatment arm was run', False, _rearm_one_arm,
     'exactly two')

def _rearm_short(m):
    m['preflight']['rearm'] = rearm_block(none_ok=0, reset_ok=2, cycles=2)
case('two cycles cannot separate a stall from one bad transfer', False,
     _rearm_short, 'REARM_INDETERMINATE')

def _rearm_cycles_lie(m):
    m['preflight']['rearm']['cycles'] = 8
case('declared cycle count exceeds what the arms recorded', False,
     _rearm_cycles_lie, 'comparable length')

# --- the denominator has to be a measured difference, not a counter read
def _no_window(m): del m['kernel_window']
case('no denominator window at all', False, _no_window,
     'missing kernel_window')

def _absolute(m):
    # The counter read once at the end: it also holds the sensitivity burst
    # and the re-arm pre-flight, so it is larger than k x B.
    m['kernel_window']['snapshots'][2]['field_value'] += 40
case('campaign delta inflated by the pre-flight', False, _absolute,
     'RELATION_BROKEN')

def _window_asserted(m):
    m['kernel_window']['code'] = 'OK'
    m['kernel_window']['campaign']['relation_ok'] = True
    m['kernel_window']['snapshots'][2]['field_value'] += 7
case('window verdict asserted against its own snapshots', False,
     _window_asserted, 'computed, not declared')

def _k_asserted(m): m['kernel_window']['k']['k'] = 1
case('k asserted rather than measured', False, _k_asserted,
     'but the snapshots give')

def _observer_reset(m):
    m['kernel_window']['snapshots'][1]['reset_generation'] = 8
case('observer reset mid-session', False, _observer_reset, 'OBSERVER_RESET')

def _b_zero(m):
    for a_ in m['attempts']:
        a_['valid'] = False
        a_['trigger_attempted'] = False
        a_['invalid_reason'] = 'not_outstanding'
    n = len(m['attempts'])
    m['denominator'].update({'B_valid': 0, 'B_invalid': n, 'kernel_delta': 0,
                             'relation_ok': False,
                             'invalid_reasons': {'not_outstanding': n}})
    m['kernel_window']['snapshots'][2]['field_value'] = \
        m['kernel_window']['snapshots'][1]['field_value']
    m['kernel_window']['campaign'] = {'delta': 0, 'expected': 0,
                                      'relation_ok': False}
    m['kernel_window']['code'] = 'NO_VALID_ATTEMPT'
case('no valid attempt in the whole batch', False, _b_zero,
     'NO_VALID_ATTEMPT')

def _wrong_field(m):
    m['kernel_window']['field'] = 'candidate_cfgn_seen'
case('differences taken from another branch\'s counter', False, _wrong_field,
     'is gated on')

def _two_snapshots(m):
    m['kernel_window']['snapshots'] = m['kernel_window']['snapshots'][:2]
case('only two snapshots', False, _two_snapshots, 'exactly three')

def _snapshots_out_of_order(m):
    m['kernel_window']['snapshots'][0]['utc'] = '2026-09-07T10:39:30Z'
case('snapshots out of order', False, _snapshots_out_of_order,
     'not in order')

# --- a fired attempt that did not qualify voids the batch
def _fired_and_invalid(m):
    m['attempts'][-1]['trigger_attempted'] = True
case('an invalid attempt whose trigger reached the wire', False,
     _fired_and_invalid, 'the batch is void')

def _valid_without_trigger(m):
    m['attempts'][0]['trigger_attempted'] = False
case('a valid attempt that never fired', False, _valid_without_trigger,
     'never issued a trigger')

def _void(m): m['denominator']['batch_void'] = True
case('batch marked void', False, _void, 'void batch carries no denominator')

# --- target facts must come from the dump that ships
def _caps_from_nowhere(m): del m['preflight']['caps']['from_sha256']
case('caps that name no dump', False, _caps_from_nowhere,
     'caps.from_sha256')

def _caps_from_another_dump(m):
    m['preflight']['caps']['from_sha256'] = sha('some-other-dump')
case('caps read from a different dump', False, _caps_from_another_dump,
     'but the shipped dump is')

def _dump_is_not_s2(m):
    m['artifacts']['dump']['sha256'] = sha('a-third-dump')
    m['preflight']['caps']['from_sha256'] = sha('a-third-dump')
case('shipped dump is not the final snapshot', False, _dump_is_not_s2,
     'not the one the window closed on')

# --- the wire witness: the harness may not mark its own work
def _no_wire(m): del m['wire']
case('no usbmon witness at all', False, _no_wire, 'missing wire')

def _wire_race(m):
    # The failure the harness structurally cannot see: it read inflight=8,
    # then the transfers completed, then the ioctl went out.
    m['wire']['attempts'][0]['wire_inflight_at_control'] = 0
    m['wire']['attempts'][0]['qualifies'] = False
    m['wire']['attempts'][0]['agree'] = False
    m['wire']['qualify_count'] -= 1
    m['wire']['agree_count'] -= 1
    m['wire']['verdict'] = 'WIRE_PRECONDITION_FAILED'
case('a transfer that completed before the trigger', False, _wire_race,
     'does not support it')

def _wire_asserted(m):
    m['wire']['attempts'][0]['wire_inflight_at_control'] = 0
case('wire row asserts agreement its numbers deny', False, _wire_asserted,
     'derive False')

def _wire_count_lie(m): m['wire']['qualify_count'] += 5
case('wire qualify_count inflated', False, _wire_count_lie,
     'rows actually qualify')

def _wire_other_capture(m): m['wire']['capture_sha256'] = sha('other-capture')
case('witness derived from a different capture', False, _wire_other_capture,
     'not the capture the manifest ships')

def _wire_missing_row(m):
    m['wire']['attempts'] = m['wire']['attempts'][1:]
    m['wire']['agree_count'] -= 1
    m['wire']['qualify_count'] -= 1
    m['wire']['attempts_fired'] -= 1
case('an attempt with no row in the witness', False, _wire_missing_row,
     'no row in the wire witness')

# --- the gadget's own queue depth, not the host's view of it
def _no_holder(m): del m['holder']
case('no gadget-side depth at all', False, _no_holder, 'missing holder')

def _holder_empty(m):
    # Host URB outstanding, function driver queue already empty. The wire
    # witness cannot see this; it is a different claim.
    m['holder']['attempts'][0]['pending_reads'] = 0
    m['holder']['attempts'][0]['meets_floor'] = False
    m['holder']['meets_floor_count'] -= 1
    m['holder']['verdict'] = 'HOLDER_BELOW_FLOOR'
case('host URB outstanding but the gadget queue was empty', False,
     _holder_empty, 'does not support it')

def _holder_asserted(m): m['holder']['attempts'][0]['pending_reads'] = 0
case('holder row asserts a floor its depth denies', False, _holder_asserted,
     'derives False')

def _holder_zero_floor(m): m['holder']['floor'] = 0
case('a floor of zero', False, _holder_zero_floor, 'asserts nothing')

def _holder_clock_paired(m): m['holder']['pairing'] = 'by_timestamp'
case('pairing two machines on their clocks', False, _holder_clock_paired,
     'imports their clock skew')

def _bad_version(m): m['manifest_version'] = 1
case('unknown manifest version', False, _bad_version, 'manifest_version')


# --- v4 provenance/correlation closures
def _holder_other_session(m):
    m['holder']['event_log_sha256'] = sha('other-holder-log')
case('holder witness copied from another event log', False,
     _holder_other_session, 'not the holder event log')

def _extra_controls(m): m['wire']['extra_controls'] = 1
case('extra matching campaign control on the wire', False, _extra_controls,
     'extra_controls must be 0')

def _extra_teardowns(m): m['holder']['extra_teardowns'] = 1
case('extra gadget teardown in campaign phase', False, _extra_teardowns,
     'extra_teardowns must be 0')

def _s0_nonatomic(m): m['kernel_window']['snapshots'][0]['snapshot_atomic'] = 0
case('S0 non-atomic even though S2 is atomic', False, _s0_nonatomic,
     'NOT_ATOMIC')

def _s1_nonatomic(m): m['kernel_window']['snapshots'][1]['snapshot_atomic'] = 0
case('S1 non-atomic even though S2 is atomic', False, _s1_nonatomic,
     'NOT_ATOMIC')

def _setup_delta_lie(m): m['preflight']['sensitivity']['setup_triggers_observed'] += 1
case('sensitivity setup count not derived from S0/S1', False,
     _setup_delta_lie, 'setup counter derives')

def _slice_lie(m): m['kernel_window']['record_slice']['start'] += 1
case('campaign record slice not S1.count..S2.count', False, _slice_lie,
     'record_slice must equal')

def main():
    fails = 0
    for name, want_ok, mutate, expect in CASES:
        m = good()
        if mutate:
            mutate(m)
        errs = validate(m)
        ok = not errs
        good_verdict = (ok == want_ok)
        matched = True
        if expect is not None and not ok:
            matched = any(expect in x for x in errs)
        status = 'ok  ' if (good_verdict and matched) else 'FAIL'
        if status == 'FAIL':
            fails += 1
        print('%s %-52s %s' % (status, name,
                               'usable' if ok else '%d reason(s)' % len(errs)))
        if status == 'FAIL':
            print('       wanted usable=%s, got usable=%s' % (want_ok, ok))
            if expect and not matched:
                print('       expected a reason containing %r' % expect)
            for x in errs[:4]:
                print('         - %s' % x)

    print()
    if fails:
        print('MANIFEST SELFTEST: %d/%d FAILED' % (fails, len(CASES)))
        return 1
    print('MANIFEST SELFTEST: %d/%d PASS' % (len(CASES), len(CASES)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
