#!/usr/bin/env python3
"""One builder for every fixture the tests use.

Fixtures used to be checked-in JSON with no generator, which is how they drift
out of step with the rules they are supposed to exercise. Everything derived is
computed here -- B from the attempt list, the campaign delta from k x B -- so a
fixture cannot quietly assert something the validator would reject.
"""
import hashlib

H = '%064x'
PROBE = 16384


def sha(n):
    return hashlib.sha256(str(n).encode()).hexdigest()


def rearm_cycle(n, progress):
    return {'n': n,
            't0': '2026-09-07T10:01:%02dZ' % (n * 2),
            't1': '2026-09-07T10:01:%02dZ' % (n * 2 + 1),
            'reenum': False, 'trigger_failed': False, 'trigger_rc': 0,
            'submitted': True, 'reaped': bool(progress),
            'first_bulk_completion_status': 0 if progress else -110,
            'bytes_after_rearm': PROBE if progress else 0,
            'REARM_DATA_PROGRESS': bool(progress)}


def rearm_block(none_ok=0, reset_ok=4, cycles=4, method='resetep'):
    """Both arms, with per-cycle primitives that actually say what the counts
    claim: a caller asking for progress_ok=n gets n cycles that really
    progressed, so a test has to state a lie explicitly to test one."""
    verdict = ('REARM_RESET_REQUIRED' if none_ok == 0 and reset_ok == cycles
               else 'REARM_NO_RESET_NEEDED'
               if none_ok == cycles and reset_ok == cycles
               else 'REARM_BROKEN')
    return {'protocol': 'two_arm_payload_progress', 'performed': True,
            'cycles': cycles, 'probe_len': PROBE, 'timeout_ms': 2000,
            'reset_method_in_use': method,
            'baseline': rearm_cycle(0, True),
            'arms': [
                {'label': 'none', 'method': 'none', 'attempted': cycles,
                 'progress_ok': none_ok, 'reenum': 0,
                 'cycles': [rearm_cycle(i + 1, i < none_ok)
                            for i in range(cycles)]},
                {'label': method, 'method': method,
                 'attempted': cycles, 'progress_ok': reset_ok, 'reenum': 0,
                 'cycles': [rearm_cycle(i + 1, i < reset_ok)
                            for i in range(cycles)]}],
            'discriminating': none_ok == 0 and reset_ok == cycles,
            'verdict': verdict}


def snapshot(label, when, t, value, dump_sha, count, causal_sync, setup_field, setup_value):
    return {'label': label, 'when': when, 'utc': t, 'ok': True,
            'path': 'r1-snapshot-%s.bin' % label, 'sha256': dump_sha,
            'field_value': value, 'reset_generation': 7, 'lost': 0,
            'caps_flags': 1, 'snapshot_atomic': 1, 'count': count,
            'causal_sync_count': causal_sync, 'setup_field': setup_field,
            'setup_value': setup_value,
            'target': [1330184202, 0, 0, 0]}


def manifest(session_id, dump_sha, b_valid, k=2, sens=20, mode='cfg0'):
    """One clean session. Every derived field is computed, never typed in:
    B from the attempt list, the campaign delta from k x B."""
    attempts = []
    for i in range(b_valid):
        attempts.append({
            'n': i + 1,
            't_arm_utc': '2026-09-07T10:%02d:%02dZ' % (5 + i // 60, i % 60),
            't_trigger_utc': '2026-09-07T10:%02d:%02dZ'
                             % (5 + i // 60, i % 60),
            'outstanding': {'checked': True, 'method': 'aio_inflight',
                            'inflight_at_trigger': 8, 'urb_completed': False},
            'trigger_attempted': True, 'trigger_rc': 0,
            'usb_bus': 1, 'usb_device': 5, 'bulk_ep': 2,
            'valid': True, 'invalid_reason': None})
    s0, s1, s2 = 100, 100 + k * sens, 100 + k * sens + k * b_valid
    return {
        'manifest_version': 2,
        'epoch': {'epoch_id': 'r1a-2026-09-07-a',
                  'artifacts': {'image': H % 1, 'observer_patch': H % 2,
                                'dwc2_r1_v9': H % 3, 'r1_gate_v9': H % 4,
                                'r1_gate_v9_1': H % 10, 'harness': H % 5,
                                'manifest_validator': H % 6,
                                'usbmon_verifier': H % 11, 'holder_merger': H % 12,
                                'verdict_generator': H % 13}},
        'session': {'session_id': session_id, 'boot_id': 'b-1111',
                    'started_utc': '2026-09-07T10:00:00Z',
                    'ended_utc': '2026-09-07T10:40:00Z', 'mode': mode,
                    'target': {'kernel_release': '7.2.0-rc5-r1',
                               'udc': '3f980000.usb',
                               'gadget_config': 'ffs.r1a'},
                    'host': {'kernel': '6.11.0', 'usbmon_bus': 1},
                    'trigger': {'bmRequestType': 0, 'bRequest': 9, 'wValue': 0 if mode=='cfg0' else 2, 'wIndex': 0, 'wLength': 0},
                    'restore_cfg': 1},
        'preflight': {
            'caps': {'g_dma': 1, 'g_dma_desc': 0, 'caps_flags': 1,
                     'source': 'dump_header', 'from_sha256': dump_sha},
            'abi': {'version': 9, 'header_size': 112, 'record_size': 80},
            'snapshot_atomic': 1, 'lost': 0, 'overlap_count': 0,
            'rearm': rearm_block(),
            'sensitivity': {'protocol': 'paired_positive_control',
                            'source': 'S0_S1_dump_headers',
                            'triggers_issued': sens,
                            'sync_owner_candidates_observed': sens,
                            'setup_triggers_observed': sens,
                            'verdict': 'SENSITIVE',
                            'excluded_windows': [
                                {'reason': 'enumeration',
                                 't0': '2026-09-07T10:00:00Z',
                                 't1': '2026-09-07T10:00:05Z'}]}},
        'kernel_window': {
            'unit': 'endpoint_stop_opportunities',
            'field': {'cfg0': 'candidate_cfg0_seen',
                      'cfgn': 'candidate_cfgn_seen'}.get(
                          mode, 'candidate_intf_seen'),
            'snapshots': [
                snapshot('S0', 'after_rearm_before_sensitivity',
                         '2026-09-07T10:01:00Z', s0, sha('s0' + session_id), 0, 10,
                         {'cfg0':'setup_cfg0_seen','cfgn':'setup_cfgn_seen'}.get(mode,'setup_intf_seen'), 100),
                snapshot('S1', 'after_sensitivity_before_campaign',
                         '2026-09-07T10:04:00Z', s1, sha('s1' + session_id), 0, 10+sens,
                         {'cfg0':'setup_cfg0_seen','cfgn':'setup_cfgn_seen'}.get(mode,'setup_intf_seen'), 100+sens),
                snapshot('S2', 'after_campaign',
                         '2026-09-07T10:39:00Z', s2, dump_sha, b_valid, 10+sens+b_valid,
                         {'cfg0':'setup_cfg0_seen','cfgn':'setup_cfgn_seen'}.get(mode,'setup_intf_seen'), 100+sens+b_valid)],
            'record_slice': {'start': 0, 'end': b_valid},
            'consistent': True,
            'k': {'measured_from': 'sensitivity_burst', 'attempts': sens,
                  'delta': k * sens, 'k': k, 'exact': True},
            'campaign': {'delta': k * b_valid, 'expected': k * b_valid,
                         'relation_ok': True},
            'code': 'OK', 'problem': None},
        'attempts': attempts,
        'denominator': {'unit': 'host_attempts', 'B_valid': b_valid,
                        'B_invalid': 0, 'batch_void': False,
                        'batch_void_reason': None,
                        'kernel_delta': k * b_valid, 'k': k,
                        'relation_ok': True, 'invalid_reasons': {}},
        'wire': {
            'protocol': 'usbmon_post_hoc',
            'evidence_strength':
                'host_controller_driver_view_at_control_submit; '
                'not a reading taken at the SETUP token',
            'capture_sha256': H % 8,
            'bus': 1, 'device': 5, 'endpoint': 2, 'b_request': 9,
            'bulk_urbs_seen': 8 * b_valid, 'control_submissions_seen': b_valid,
            'attempts_fired': b_valid, 'extra_controls': 0,
            'agree_count': b_valid, 'qualify_count': b_valid,
            'attempts': [
                {'n': i + 1, 'control_us': 1000000 + i * 1000,
                 'control_setup': '00 09 0000 0000 0000',
                 'wire_inflight_at_control': 8,
                 'internal_inflight_at_trigger': 8,
                 'bulk_completed_within_control': 8,
                 'agree': True, 'qualifies': True} for i in range(b_valid)],
            'verdict': 'WIRE_CONFIRMED'},
        'holder': {
            'protocol': 'device_teardown_depth',
            'evidence_strength':
                'depth when the function harness reaped the DISABLE event; '
                'depth >= floor is evidence the holder was non-empty across '
                'the teardown, depth == 0 is ambiguous and is refused, not '
                'concluded from',
            'pairing': 'by_order_not_by_clock', 'floor': 1,
            'event_log_sha256': H % 14, 'session_id': session_id, 'boot_id': 'b-1111',
            'device_teardowns_seen': b_valid, 'attempts_fired': b_valid,
            'extra_teardowns': 0, 'meets_floor_count': b_valid,
            'skew_s_min': -0.004, 'skew_s_max': 0.011,
            'attempts': [
                {'n': i + 1, 'device_seq': i + 1, 'pending_reads': 8,
                 'meets_floor': True,
                 'host_t_trigger_utc': '2026-09-07T10:05:00Z',
                 'device_t_utc': '2026-09-07T10:05:00.500Z',
                 'skew_s': 0.5} for i in range(b_valid)],
            'verdict': 'HOLDER_CONFIRMED'},
        'artifacts': {'dump': {'path': 'r1-snapshot-S2.bin',
                               'sha256': dump_sha},
                      'usbmon': {'path': 'batch.mon', 'sha256': H % 8, 'scope': 'campaign_only'},
                      'harness_log': {'path': 'batch.log', 'sha256': H % 9},
                      'holder_event_log': {'path': 'dev-events.jsonl', 'sha256': H % 14}},
    }
