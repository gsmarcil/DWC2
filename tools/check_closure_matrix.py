#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

MATRIX_PATH = Path('docs/CLOSURE-MATRIX.json')
PATCH_PATH = Path('r1a-device/instrumentation/R1A-RESET-INSTRUMENTATION-v5.patch')
RECEIPT_PATH = Path('r1a-device/instrumentation/R1A-RESET-INSTRUMENTATION-v5.RECEIPT.txt')
VERIFIER_PATH = Path('VERIFY-REPOSITORY.sh')
EXPECTED_KERNEL_PIN = 'f5a7e2ae5f0a9a5caf59501457938eeb249a7dc8'

REQUIRED_DIMENSIONS = (
    'source_pin', 'standalone_apply', 'measurement_disabled_build',
    'measurement_enabled_build', 'target_arm64_build', 'campaign_composition',
    'functional_semantics_preservation', 'event_ordering',
    'diagnostic_mmio_excluded', 'timing_perturbation_sensitivity',
    'mapping_lineage_design', 'consumer_compatibility', 'negative_controls',
    'cross_tree_duplicate_census', 'provenance', 'documentation_sync',
    'runtime_requirements', 'runtime_execution', 'run_epoch_binding',
    'hypothesis_result',
    'external_evidence_boundary', 'impact_claim_boundary',
    'continuous_enforcement',
)

# A dimension may block the run, the admissibility of the resulting evidence, or
# only a NEGATIVE closure. Mixing these produced a circular gate in v1, where
# the campaign could not be READY until the campaign had already run.
BLOCK_KINDS = {'run_readiness', 'evidence_admissibility', 'negative_closure', 'none'}

# Policy, not data. v2 let the matrix declare which verdict a row blocked, so a
# row could be demoted to 'none' and vanish from a verdict without ever being
# closed. The map is canonical here and the matrix must agree with it.
# The closing invariant, enforced rather than described:
#
#   No PASS may rest solely on a state file, a "receipt=PASS" line, or a
#   non-empty metadata field. Every PASS must end in an artifact plus an
#   independent predicate.
#
# Each dimension declares what its PASS actually rests on. Rows marked
# declaration_only are mechanically barred from reading PASS, so a row cannot
# quietly graduate on an assertion; closing it requires moving it to a derived
# kind AND writing the predicate that earns it.
DERIVATION = {
    'source_pin': 'digest_recomputed',
    'standalone_apply': 'declaration_only',
    'measurement_disabled_build': 'declaration_only',
    'measurement_enabled_build': 'declaration_only',
    'target_arm64_build': 'declaration_only',
    'campaign_composition': 'declaration_only',
    'functional_semantics_preservation': 'checker_executed',
    'event_ordering': 'structural_predicate',
    'diagnostic_mmio_excluded': 'structural_predicate',
    'timing_perturbation_sensitivity': 'declaration_only',
    'mapping_lineage_design': 'structural_predicate',
    'consumer_compatibility': 'adversarial_fixtures',
    'negative_controls': 'wiring_inspected',
    'cross_tree_duplicate_census': 'wiring_inspected',
    'provenance': 'wiring_inspected',
    'documentation_sync': 'wiring_inspected',
    'runtime_requirements': 'content_predicate',
    'runtime_execution': 'declaration_only',
    'run_epoch_binding': 'partial_binding',
    'hypothesis_result': 'declaration_only',
    'external_evidence_boundary': 'content_predicate',
    'impact_claim_boundary': 'content_predicate',
    'continuous_enforcement': 'external_snapshot',
}
DECLARATION_ONLY = {'declaration_only', 'partial_binding'}

EXPECTED_BLOCKS = {
    'measurement_disabled_build': 'run_readiness',
    'measurement_enabled_build': 'run_readiness',
    'target_arm64_build': 'run_readiness',
    'campaign_composition': 'run_readiness',
    'functional_semantics_preservation': 'run_readiness',
    'event_ordering': 'evidence_admissibility',
    'diagnostic_mmio_excluded': 'evidence_admissibility',
    'mapping_lineage_design': 'evidence_admissibility',
    'consumer_compatibility': 'evidence_admissibility',
    'runtime_execution': 'evidence_admissibility',
    'run_epoch_binding': 'evidence_admissibility',
    'timing_perturbation_sensitivity': 'negative_closure',
}
ALLOWED_RUNTIME = {'NOT_RUN', 'VALID_RUN', 'INVALID_RUN'}
ALLOWED_HYPOTHESIS = {'UNDETERMINED', 'PROVEN', 'DISPROVEN', 'CONFIG_SCOPED_NEGATIVE'}
ALLOWED_REVIEW_STATES = {'PASS', 'OPEN', 'FAIL'}
ALLOWED_CAMPAIGN = {'READY', 'BLOCKED'}
OPEN_RECEIPT_STATES = {'NOT_RUN', 'UNVERIFIED', 'UNKNOWN', 'NOT_EXECUTED'}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def read_text(root: Path, rel) -> str:
    return (root / rel).read_text(encoding='utf-8')


def parse_receipt(text: str) -> dict:
    out = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key, value = key.strip(), value.strip()
        if key in out:
            raise ValueError(f'duplicate receipt key: {key}')
        out[key] = value
    return out


def state_from_receipt(value):
    if value == 'PASS':
        return 'PASS'
    if value in OPEN_RECEIPT_STATES or value is None:
        return 'OPEN'
    return 'FAIL'


def all_tokens(text: str, tokens) -> bool:
    return all(token in text for token in tokens)


def consumer_fixtures() -> dict:
    """Traces the reviewer generates, so the consumer is tested by this checker.

    One good trace that must be accepted, and one per rejection the contract
    requires. The good trace exists so a consumer that rejects everything, which
    would carry no information, cannot pass.
    """
    def rec(stage, **kw):
        base = {'stage': stage, 'req_id': 1, 'map_id': 1, 'dma': 4096,
                'reset_id': 0, 'flags': 0}
        base.update(kw)
        return json.dumps(base)

    good = [rec('MAP'), rec('DMA_ADDR_WRITTEN'), rec('EP_ARMED'),
            rec('EPDIS_WRITTEN'), rec('WAIT_RETURN'), rec('PRE_U'),
            rec('UNMAP_BEGIN'), rec('UNMAP_DONE')]
    join = lambda rows: '\n'.join(rows) + '\n'
    return {
        'good': join(good),
        'diag_build': join([rec('MAP', flags=128)] + good[1:]),
        'req_mismatch': join(good[:4] + [rec('WAIT_RETURN', req_id=2)] + good[5:]),
        'map_mismatch': join(good[:4] + [rec('WAIT_RETURN', map_id=99)] + good[5:]),
        'dma_mismatch': join(good[:4] + [rec('WAIT_RETURN', dma=8192)] + good[5:]),
        'missing_event': join([r for r in good if 'UNMAP_DONE' not in r]),
        'wrong_order': join(good[:3] + [good[5], good[4]] + good[6:]),
        'reset_epoch_mismatch': join(good[:6] + [rec('UNMAP_BEGIN', reset_id=7)] + good[7:]),
    }


def compute_states(root: Path):
    errors = []
    states = {k: 'FAIL' for k in REQUIRED_DIMENSIONS}
    for rel in (PATCH_PATH, RECEIPT_PATH, VERIFIER_PATH):
        if not (root / rel).is_file():
            errors.append(f'missing required audit input: {rel.as_posix()}')
    if errors:
        return states, errors

    patch = read_text(root, PATCH_PATH)
    receipt_text = read_text(root, RECEIPT_PATH)
    verifier = read_text(root, VERIFIER_PATH)
    try:
        receipt = parse_receipt(receipt_text)
    except ValueError as exc:
        return states, [str(exc)]

    states['source_pin'] = 'PASS' if (
        receipt.get('kernel_pin') == EXPECTED_KERNEL_PIN and
        receipt.get('patch_sha256') == sha256(root / PATCH_PATH)) else 'FAIL'
    # Was PASS from three receipt lines, with no apply re-executed. Under the
    # closing invariant a receipt line is not a derivation, so this can only be
    # OPEN until an apply is re-run against the pinned tree, or the receipt is
    # bound to a verifiable CI artifact.
    states['standalone_apply'] = 'OPEN' if all(
        receipt.get(k) == 'PASS' for k in
        ('standalone_apply_to_pin', 'whitespace_error_all', 'diff_check')) else 'FAIL'
    states['measurement_disabled_build'] = state_from_receipt(receipt.get('build_measurement_disabled'))
    states['measurement_enabled_build'] = state_from_receipt(receipt.get('build_measurement_enabled'))
    states['target_arm64_build'] = state_from_receipt(receipt.get('criterion_5_arm64_build'))
    states['campaign_composition'] = state_from_receipt(receipt.get('criterion_4_campaign_composition'))
    # v1 promoted this on a receipt line alone, which is the exact
    # "claim is not proof" failure the matrix exists to prevent. It now needs an
    # executed checker as well; the receipt line alone can only keep it OPEN.
    fsp = root / 'tools/check_functional_semantics.py'
    states['functional_semantics_preservation'] = 'OPEN'
    if receipt.get('criterion_6_functional_semantics_preservation') == 'PASS':
        if fsp.is_file() and all_tokens(verifier, ['functional_semantics']):
            try:
                proc = subprocess.run([sys.executable, str(fsp), '.'], cwd=str(root),
                                      capture_output=True, text=True, timeout=120)
                states['functional_semantics_preservation'] = (
                    'PASS' if proc.returncode == 0 else 'FAIL')
            except Exception:
                states['functional_semantics_preservation'] = 'OPEN'

    # Structural, not token presence: the event must appear AFTER the register
    # write and BEFORE the wait. Token checks alone would stay green if someone
    # moved the emit back above dwc2_set_bit().
    # The post-image: added lines PLUS context lines. Restricting to added
    # lines was wrong, and the real v5 patch proved it: the dwc2_set_bit() call
    # the event must follow is unchanged context, so an added-only view could
    # never see the ordering it claims to check.
    added = '\n'.join(
        l[1:] for l in patch.splitlines()
        if (l.startswith('+') and not l.startswith('+++')) or l.startswith(' '))
    def order_ok(text):
        try:
            w = text.index('DXEPCTL_EPDIS | DXEPCTL_SNAK')
            e = text.index('DWC2_R1_EPDIS_WRITTEN', w)
            q = text.index('DXEPINT_EPDISBLD', e)
        except ValueError:
            return False
        return w < e < q
    def addr_before_arm(text):
        # Enum members carry both names, so matching the names alone succeeded
        # on the declaration order and measured nothing. Anchor on the CALL
        # sites and on the register writes they must follow.
        try:
            dma_w = text.index('dwc2_writel(hsotg, ureq->dma, dma_reg)')
            a = text.index('dwc2_r1_measure_dma_addr_written(', dma_w)
            arm_w = text.index('dwc2_writel(hsotg, ctrl, epctrl_reg)', a)
            b = text.index('dwc2_r1_measure_ep_armed(', arm_w)
        except ValueError:
            return False
        return dma_w < a < arm_w < b
    states['event_ordering'] = 'PASS' if (
        all_tokens(receipt_text, ['criterion_1_epdis_event_after_write=PASS',
                                  'criterion_3_programmed_split=PASS']) and
        'DWC2_R1_EPDIS_ASSERT' not in patch and
        order_ok(added) and addr_before_arm(added)) else 'FAIL'

    # What v5 actually proves: the diagnostic MMIO is compiled out. That is a
    # real property and it is checked structurally, by requiring the reads to
    # sit inside the DIAG ifdef in the added lines.
    # Every DIAG region is inspected, not only the first. v5 has two: the build
    # flag definition and the register snapshot. Checking only the first found
    # the flag region, saw no MMIO in it, and wrongly reported the reads
    # unguarded. The reads must be inside SOME diagnostic region, and must not
    # appear outside all of them.
    def diag_regions(text):
        out, i = [], 0
        while True:
            i = text.find('#ifdef CONFIG_USB_DWC2_R1_MEASURE_DIAG', i)
            if i < 0:
                break
            j = text.find('#endif', i)
            out.append(text[i:j if j > 0 else len(text)])
            i = j if j > 0 else len(text)
        return out
    regions = diag_regions(added)
    outside = added
    for reg in regions:
        outside = outside.replace(reg, '')
    # All three snapshot registers, not just the first. Moving DOEPINT or
    # DOEPTSIZ outside the guard would have gone undetected.
    SNAP_REGS = ('DOEPCTL', 'DOEPINT', 'DOEPTSIZ')
    diag_guarded = all(
        any(f'dwc2_readl(hsotg, {r}(' in reg for reg in regions) and
        f'dwc2_readl(hsotg, {r}(' not in outside
        for r in SNAP_REGS)
    states['diagnostic_mmio_excluded'] = 'PASS' if (
        all_tokens(receipt_text, ['criterion_2_zero_mmio_in_decisive_window=PASS']) and
        diag_guarded and
        all_tokens(patch, ['config USB_DWC2_R1_MEASURE_DIAG', 'default n',
                           'DWC2_R1_FLAG_DIAG_BUILD BIT(7)', 'A NEGATIVE result does',
                           'Say N for the campaign build.'])) else 'FAIL'

    # What v5 does NOT prove: that the remaining tracepoint calls add no delay.
    # WAIT_RETURN, PRE_U and UNMAP_BEGIN still execute between the stop timeout
    # and the unmap. This is a timing hypothesis, so any added latency there can
    # bias a NEGATIVE result toward safe. It cannot manufacture a positive one.
    # Closing it needs a measured sensitivity result, not a source reading.
    states['timing_perturbation_sensitivity'] = state_from_receipt(
        receipt.get('timing_perturbation_sensitivity'))

    # Token presence proved only that the names exist. The identity must be
    # assigned at MAP and emitted by the shared emitter, so every stage carries
    # the same lineage rather than each inventing its own.
    lineage_assigned = all(f'hs_req->{f} =' in added or f'hs_req->{f}++' in added
                           for f in ('r1_req_id', 'r1_map_id', 'r1_dma'))
    lineage_emitted = all(f'hs_req->{f}' in added for f in ('r1_req_id', 'r1_map_id'))
    stages_present = all_tokens(patch, ['DWC2_R1_MAP', 'DWC2_R1_DMA_ADDR_WRITTEN',
                                        'DWC2_R1_UNMAP_BEGIN', 'DWC2_R1_UNMAP_DONE'])
    states['mapping_lineage_design'] = 'PASS' if (
        lineage_assigned and lineage_emitted and stages_present) else 'FAIL'

    # v1 closed this on two empty files plus two names in the verifier. It never
    # ran anything. A consumer that cannot reject a bad trace cannot adjudicate
    # a negative result, so the selftest is EXECUTED and must announce the
    # rejections it actually performs.
    consumer = root / 'tools/validate_r1_lifetime_trace.py'
    consumer_test = root / 'tools/validate_r1_lifetime_trace_selftest.py'
    REQUIRED_REJECTIONS = ('diag_build', 'req_mismatch', 'map_mismatch',
                           'dma_mismatch', 'missing_event', 'wrong_order',
                           'reset_epoch_mismatch')
    # v2 trusted the consumer's own selftest to announce its rejections, which a
    # selftest could satisfy by printing the words and exiting 0. The reviewer
    # must hold the negative controls: this checker generates each bad trace
    # itself and requires the consumer to reject it, plus one good trace it must
    # accept, so a checker that rejects everything fails too.
    states['consumer_compatibility'] = 'OPEN'
    if (consumer.is_file() and consumer_test.is_file() and
            all_tokens(verifier, ['validate_r1_lifetime_trace_selftest.py',
                                  'validate_r1_lifetime_trace.py'])):
        try:
            own = subprocess.run([sys.executable, str(consumer_test), 'selftest'],
                                 cwd=str(root), capture_output=True, text=True,
                                 timeout=120)
            ok = own.returncode == 0
            with tempfile.TemporaryDirectory() as td:
                for name, trace in consumer_fixtures().items():
                    f = Path(td) / f'{name}.jsonl'
                    f.write_text(trace, encoding='utf-8')
                    r = subprocess.run([sys.executable, str(consumer), str(f)],
                                       cwd=str(root), capture_output=True,
                                       text=True, timeout=60)
                    should_accept = (name == 'good')
                    if (r.returncode == 0) != should_accept:
                        ok = False
                        errors.append(f'consumer mishandled fixture {name}: '
                                      f'rc={r.returncode}, expected '
                                      f'{"accept" if should_accept else "reject"}')
            states['consumer_compatibility'] = 'PASS' if ok else 'FAIL'
        except Exception as exc:
            errors.append(f'consumer could not be exercised: {exc}')
            states['consumer_compatibility'] = 'OPEN'

    states['negative_controls'] = 'PASS' if all_tokens(verifier, [
        'verify_holder_contract_selftest.py', 'holder_log_guard_selftest.py',
        'holder_roundtrip.py', 'duplicate_census_selftest',
        'verify_status_sync_selftest.py', 'closure_matrix_selftest']) else 'FAIL'

    states['cross_tree_duplicate_census'] = 'PASS' if (
        all(p.is_file() for p in (root / 'tools/check_duplicates_full.py',
                                  root / 'DUPLICATES-OVERLAY.txt')) and
        all_tokens(verifier, ['duplicate_census_selftest', 'duplicate_census:.'])) else 'FAIL'

    states['provenance'] = 'PASS' if (
        all(p.is_file() for p in (root / 'verify_archive_tracking.py',
                                  root / 'baseline/SHA256SUMS')) and
        all_tokens(verifier, ['archive_tracking_proof',
                              'python3 verify_archive_tracking.py "$ROOT"'])) else 'FAIL'

    states['documentation_sync'] = 'PASS' if (
        all(p.is_file() for p in (root / 'verify_status_sync.py',
                                  root / 'verify_status_sync_selftest.py')) and
        all_tokens(verifier, ['status_sync_selftest', 'python3 verify_status_sync.py'])) else 'FAIL'

    pending_path = root / 'docs/PENDING.md'
    if pending_path.is_file():
        pending = pending_path.read_text(encoding='utf-8')
        states['runtime_requirements'] = 'PASS' if all_tokens(pending, [
            'real DWC2 gadget UDC', 'g_dma=1', 'g_dma_desc=0', 'observer ABI=9',
            'snapshot_atomic=1', 'lost=0', 'usbmon + device holder evidence',
            'UNMAP_DONE(iova,len,device)', 'NO_REMAP(retired_range)',
            'post-unmap transaction/fault to retired range']) else 'FAIL'
        states['external_evidence_boundary'] = 'PASS' if all_tokens(pending, [
            'MIRROR_VERIFIED / ORIGINAL_PENDING',
            'does NOT       establish that Linux DWC2 carries the defect under study.',
            'Linux K_hw     UNDETERMINED']) else 'FAIL'
    else:
        states['runtime_requirements'] = 'FAIL'
        states['external_evidence_boundary'] = 'FAIL'

    # v1 had no branch producing PASS here, so running the campaign would have
    # moved this OPEN -> FAIL. Execution validity and hypothesis outcome are now
    # separate axes: a valid run that disproves the hypothesis is a PASS for the
    # run and a DISPROVEN for the result, not a failure of either.
    rs = root / 'docs/RUNTIME-STATE.txt'
    runtime_state, hypothesis = 'NOT_RUN', 'UNDETERMINED'
    if rs.is_file():
        rec = parse_receipt(rs.read_text(encoding='utf-8'))
        runtime_state = rec.get('runtime_execution', 'NOT_RUN')
        hypothesis = rec.get('hypothesis_result', 'UNDETERMINED')
    if runtime_state not in ALLOWED_RUNTIME:
        errors.append(f'invalid runtime_execution state: {runtime_state!r}')
        runtime_state = 'INVALID_RUN'
    if hypothesis not in ALLOWED_HYPOTHESIS:
        errors.append(f'invalid hypothesis_result: {hypothesis!r}')
        hypothesis = 'UNDETERMINED'
    # VALID_RUN asserted in a text file is a declaration, not a derivation, so
    # it can only hold the row OPEN. An INVALID_RUN still fails, because a
    # self-declared failure needs no corroboration to be believed.
    states['runtime_execution'] = {'NOT_RUN': 'OPEN', 'VALID_RUN': 'OPEN',
                                   'INVALID_RUN': 'FAIL'}[runtime_state]
    # The result axis is never a gate failure. An undetermined hypothesis is an
    # open question, and a disproof is a finding, not a defect.
    # v2 let any non-UNDETERMINED token become PASS, so editing one word in a
    # text file could declare the hypothesis proven. The outcome must be
    # consistent with the run that produced it, and admissibility is checked by
    # the matrix layer, not asserted here.
    # Consistency with the run is necessary but not sufficient. Swapping
    # DISPROVEN for PROVEN in a text file must not move this row, so a
    # determined outcome stays OPEN until an adjudicator derives it from the
    # trace. The consistency check below is kept because it still catches
    # incoherent pairs.
    if hypothesis == 'UNDETERMINED':
        states['hypothesis_result'] = 'OPEN'
    elif runtime_state != 'VALID_RUN':
        errors.append(f'hypothesis_result {hypothesis} requires runtime_execution'
                      f'=VALID_RUN, got {runtime_state}')
        states['hypothesis_result'] = 'FAIL'
    else:
        states['hypothesis_result'] = 'OPEN'

    # Epoch binding: the run must be tied to the artifacts that closed readiness,
    # or gates closed later could retroactively bless an older kernel.
    EPOCH_FIELDS = ('epoch_id', 'kernel_commit', 'kernel_build_id', 'patch_sha256',
                    'config_sha256', 'device_harness_sha256', 'host_harness_sha256',
                    'observer_contract', 'boot_id')
    epoch = root / 'docs/RUN-EPOCH.txt'
    states['run_epoch_binding'] = 'OPEN'
    if epoch.is_file():
        rec = parse_receipt(epoch.read_text(encoding='utf-8'))
        # Only patch_sha256 and kernel_commit are bound to anything. The rest
        # are required to be present but are not yet compared to an artifact,
        # which is why this row's derivation kind is partial_binding and it
        # cannot read PASS under the closing invariant.
        missing = [f for f in EPOCH_FIELDS if not rec.get(f)]
        if missing:
            errors.append('run epoch missing fields: ' + ', '.join(missing))
            states['run_epoch_binding'] = 'FAIL'
        elif rec.get('patch_sha256') != receipt.get('patch_sha256'):
            errors.append('run epoch patch_sha256 does not match the instrumentation receipt')
            states['run_epoch_binding'] = 'FAIL'
        elif rec.get('kernel_commit') != EXPECTED_KERNEL_PIN:
            errors.append('run epoch kernel_commit is not the pinned kernel')
            states['run_epoch_binding'] = 'FAIL'
        else:
            states['run_epoch_binding'] = 'OPEN'
    elif runtime_state != 'NOT_RUN':
        errors.append('a run is declared but docs/RUN-EPOCH.txt is absent')
        states['run_epoch_binding'] = 'FAIL'

    impact_path = root / 'docs/IMPACT-ANALYSIS.md'
    if impact_path.is_file():
        impact = impact_path.read_text(encoding='utf-8')
        states['impact_claim_boundary'] = 'PASS' if all_tokens(impact, [
            'Does not move the evidence ladder.',
            'DMA is definitely still active when unmap occurs.',
            'That remains `UNKNOWN` and is the closure gate of this document.',
            '## 2. The closure gate (UNKNOWN)']) else 'FAIL'
    else:
        states['impact_claim_boundary'] = 'FAIL'

    # Recorded as observed rather than merely unknown. Branch protection and
    # required checks are off, and no ruleset is configured, so the gate is not
    # enforced by the host today. Not campaign-blocking, but not a blank either.
    states['continuous_enforcement'] = 'OPEN'

    # The closing invariant applied to the computed layer, generically.
    # v4 enforced it only where the matrix declared PASS, and patched the
    # computed side one row at a time (standalone_apply pinned to OPEN,
    # hypothesis_result pinned to OPEN). Rows such as measurement_enabled_build
    # still reached PASS internally from state_from_receipt(), so editing one
    # word in a receipt moved a row the invariant says a receipt cannot move.
    # One rule instead of three special cases: no declaration_only row may
    # leave this function reading PASS, whatever produced it. The asymmetry is
    # deliberate and preserved - an unverified declaration of success is
    # demoted to OPEN and reported as a checker defect, while a declaration of
    # INVALID/FAIL still fails, because a self-declared failure needs no
    # corroboration to be believed.
    for ident, kind in DERIVATION.items():
        if kind in DECLARATION_ONLY and states.get(ident) == 'PASS':
            errors.append(f'{ident}: uncorroborated PASS from {kind}')
            states[ident] = 'OPEN'
    return states, errors


def validate_matrix(root: Path, matrix_path: Path = MATRIX_PATH):
    errors = []
    path = root / matrix_path
    if not path.is_file():
        return [f'missing matrix: {matrix_path.as_posix()}']
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc:
        return [f'invalid matrix JSON: {exc}']

    if data.get('schema_version') != 4:
        errors.append(f"schema_version must be 4, got {data.get('schema_version')!r}")
    if not isinstance(data.get('contract_id'), str) or not data['contract_id'].strip():
        errors.append('contract_id must be a non-empty string')

    dims = data.get('dimensions')
    if not isinstance(dims, list):
        return errors + ['dimensions must be a list']

    by_id = {}
    for idx, dim in enumerate(dims):
        if not isinstance(dim, dict):
            errors.append(f'dimensions[{idx}] must be an object'); continue
        ident = dim.get('id')
        if not isinstance(ident, str) or not ident:
            errors.append(f'dimensions[{idx}] has invalid id'); continue
        if ident in by_id:
            errors.append(f'duplicate dimension id: {ident}'); continue
        by_id[ident] = dim

    missing = [d for d in REQUIRED_DIMENSIONS if d not in by_id]
    extra = [d for d in by_id if d not in REQUIRED_DIMENSIONS]
    if missing:
        errors.append('missing required dimensions: ' + ', '.join(missing))
    if extra:
        errors.append('unknown dimensions: ' + ', '.join(extra))

    observed, obs_errors = compute_states(root)
    errors.extend(obs_errors)

    for ident in REQUIRED_DIMENSIONS:
        dim = by_id.get(ident)
        if dim is None:
            continue
        declared = dim.get('review_state')
        if declared not in ALLOWED_REVIEW_STATES:
            errors.append(f'{ident}: invalid review_state {declared!r}')
        elif declared != observed.get(ident):
            errors.append(f'{ident}: matrix says {declared}, repository computes {observed.get(ident)}')
        if not isinstance(dim.get('evidence_state'), str) or not dim['evidence_state'].strip():
            errors.append(f'{ident}: evidence_state must be non-empty')
        if 'blocks_campaign' in dim:
            errors.append(f'{ident}: blocks_campaign is a v1 field; use blocks')
        sources = dim.get('sources')
        if not isinstance(sources, list) or not sources:
            errors.append(f'{ident}: sources must be a non-empty list')
        else:
            for src in sources:
                if not isinstance(src, str) or not src:
                    errors.append(f'{ident}: invalid source entry {src!r}')
                elif src.startswith('external:'):
                    continue
                elif not (root / src).exists():
                    errors.append(f'{ident}: source does not exist: {src}')
        kind = DERIVATION.get(ident)
        # The matrix carried a derivation field that nothing read. A row could
        # declare standalone_apply.derivation = structural_predicate while the
        # checker knew it was declaration_only, and the gate stayed green: the
        # document said the PASS was earned, and no control compared the claim
        # to the policy. Policy lives in DERIVATION; the matrix must agree.
        declared_kind = dim.get('derivation')
        if declared_kind != kind:
            errors.append(
                f'{ident}: matrix derivation {declared_kind!r} '
                f'!= checker derivation {kind!r}')
        if kind is None:
            errors.append(f'{ident}: no derivation kind declared')
        elif declared == 'PASS' and kind in DECLARATION_ONLY:
            errors.append(
                f'{ident}: PASS rests on {kind}; a state file, a receipt line or a '
                f'metadata field is not a derivation. Close it with an artifact and '
                f'an independent predicate, and move its derivation kind.')
        if declared == 'OPEN' and not (isinstance(dim.get('close_artifact'), str) and dim['close_artifact'].strip()):
            errors.append(f'{ident}: OPEN requires close_artifact')
        if declared == 'FAIL' and not (isinstance(dim.get('blocker'), str) and dim['blocker'].strip()):
            errors.append(f'{ident}: FAIL requires blocker')

    # v1 asked one question and made it circular: runtime_execution blocked the
    # campaign, so the campaign could never be READY until it had already run.
    # Two independent questions instead.
    for ident, dim in by_id.items():
        kind = dim.get('blocks')
        if kind not in BLOCK_KINDS:
            errors.append(f'{ident}: blocks must be one of {sorted(BLOCK_KINDS)}, got {kind!r}')
        expected = EXPECTED_BLOCKS.get(ident, 'none')
        if kind != expected:
            errors.append(f'{ident}: blocks must be {expected!r} by policy, matrix says {kind!r}')

    def rows_pass(kind):
        rows = [d for d in REQUIRED_DIMENSIONS if EXPECTED_BLOCKS.get(d) == kind]
        return bool(rows) and all(by_id.get(d, {}).get('review_state') == 'PASS'
                                  for d in rows)

    # Hierarchical, not parallel. v2 computed each verdict from its own rows
    # only, so evidence could read READY while the builds that produced it were
    # still open, and a negative closure could read READY on top of inadmissible
    # evidence. NEGATIVE => EVIDENCE => RUN.
    run_ok = rows_pass('run_readiness')
    evid_ok = run_ok and rows_pass('evidence_admissibility')
    neg_ok = evid_ok and rows_pass('negative_closure')
    computed = {'run_readiness': 'READY' if run_ok else 'BLOCKED',
                'evidence_admissibility': 'READY' if evid_ok else 'BLOCKED',
                'negative_closure_admissibility': 'READY' if neg_ok else 'BLOCKED'}
    for key, value in computed.items():
        declared = data.get(key)
        if declared not in ALLOWED_CAMPAIGN:
            errors.append(f'invalid {key} {declared!r}')
        elif declared != value:
            errors.append(f'{key}: matrix says {declared}, computed {value}')
    return errors


def run(root: Path) -> int:
    errors = validate_matrix(root)
    if errors:
        print('CLOSURE_MATRIX: FAIL', file=sys.stderr)
        for e in errors:
            print('  ' + e, file=sys.stderr)
        return 1
    data = json.loads((root / MATRIX_PATH).read_text(encoding='utf-8'))
    dims = {d['id']: d for d in data['dimensions']}
    open_dims = [d for d in REQUIRED_DIMENSIONS if dims[d]['review_state'] == 'OPEN']
    print('CLOSURE_MATRIX: PASS')
    print(f"  contract_id              {data['contract_id']}")
    print(f"  coverage                 {len(REQUIRED_DIMENSIONS)}/{len(REQUIRED_DIMENSIONS)} dimensions")
    print(f"  run_readiness            {data['run_readiness']}")
    print(f"  evidence_admissibility   {data['evidence_admissibility']}")
    print(f"  negative_closure         {data['negative_closure_admissibility']}")
    print('  open_dimensions          ' + (', '.join(open_dims) if open_dims else 'none'))
    return 0


def fixture_matrix(states=None) -> dict:
    base = {
        'source_pin': 'PASS', 'standalone_apply': 'OPEN',
        'measurement_disabled_build': 'OPEN', 'measurement_enabled_build': 'OPEN',
        'target_arm64_build': 'OPEN', 'campaign_composition': 'OPEN',
        'functional_semantics_preservation': 'OPEN', 'event_ordering': 'PASS',
        'diagnostic_mmio_excluded': 'PASS',
        'timing_perturbation_sensitivity': 'OPEN',
        'mapping_lineage_design': 'PASS', 'consumer_compatibility': 'OPEN',
        'negative_controls': 'PASS', 'cross_tree_duplicate_census': 'PASS',
        'provenance': 'PASS', 'documentation_sync': 'PASS',
        'runtime_requirements': 'PASS', 'runtime_execution': 'OPEN',
        'run_epoch_binding': 'OPEN', 'hypothesis_result': 'OPEN', 'external_evidence_boundary': 'PASS',
        'impact_claim_boundary': 'PASS', 'continuous_enforcement': 'OPEN',
    }
    if states:
        base.update(states)
    BLOCKS = EXPECTED_BLOCKS
    dims = []
    for ident in REQUIRED_DIMENSIONS:
        state = base[ident]
        dim = {'id': ident, 'review_state': state, 'evidence_state': 'fixture',
               'blocks': BLOCKS.get(ident, 'none'), 'sources': ['STATUS.md'],
               'derivation': DERIVATION.get(ident)}
        if state == 'OPEN':
            dim['close_artifact'] = 'fixture close artifact'
        if state == 'FAIL':
            dim['blocker'] = 'fixture blocker'
        dims.append(dim)

    def rows_pass(kind):
        rows = [d for d in dims if d['blocks'] == kind]
        return bool(rows) and all(d['review_state'] == 'PASS' for d in rows)

    run_ok = rows_pass('run_readiness')
    evid_ok = run_ok and rows_pass('evidence_admissibility')
    neg_ok = evid_ok and rows_pass('negative_closure')
    return {'schema_version': 4, 'contract_id': 'fixture-v4',
            'run_readiness': 'READY' if run_ok else 'BLOCKED',
            'evidence_admissibility': 'READY' if evid_ok else 'BLOCKED',
            'negative_closure_admissibility': 'READY' if neg_ok else 'BLOCKED',
            'dimensions': dims}


GOOD_PATCH = """--- a/x
+++ b/x
+config USB_DWC2_R1_MEASURE_DIAG
+\tdefault n
+A NEGATIVE result does
+Say N for the campaign build.
+#define DWC2_R1_FLAG_DIAG_BUILD BIT(7)
+\tdwc2_set_bit(hsotg, epctrl_reg, DXEPCTL_EPDIS | DXEPCTL_SNAK);
+\tdwc2_r1_measure_event(DWC2_R1_EPDIS_WRITTEN);
+\tdwc2_hsotg_wait_bit_set(hsotg, epint_reg, DXEPINT_EPDISBLD, 100);
+\t\t\tdwc2_writel(hsotg, ureq->dma, dma_reg);
+\t\t\tdwc2_r1_measure_dma_addr_written(hsotg, hs_ep, hs_req, ureq->dma);
+\t\t\t/* stage DWC2_R1_DMA_ADDR_WRITTEN */
+\tdwc2_writel(hsotg, ctrl, epctrl_reg);
+\tdwc2_r1_measure_ep_armed(hsotg, hs_ep, hs_req, true);
+#ifdef CONFIG_USB_DWC2_R1_MEASURE_DIAG
+\t\tepctl = dwc2_readl(hsotg, DOEPCTL(hs_ep->index));
+\t\tepint = dwc2_readl(hsotg, DOEPINT(hs_ep->index));
+\t\tepsiz = dwc2_readl(hsotg, DOEPTSIZ(hs_ep->index));
+#endif
+\ths_req->r1_req_id = 1;
+\ths_req->r1_map_id = 1;
+\ths_req->r1_dma = hs_req->req.dma;
+\tevent_dma = hs_req->r1_dma;
+\tdwc2_r1_emit(hsotg, hs_ep, hs_req, DWC2_R1_MAP, hs_req->r1_req_id, hs_req->r1_map_id);
+\tDWC2_R1_UNMAP_BEGIN DWC2_R1_UNMAP_DONE
"""


def write_fixture(root: Path, patch_text: str = GOOD_PATCH) -> None:
    for rel in ['docs', 'r1a-device/instrumentation', 'tools', 'baseline',
                '.github/workflows']:
        (root / rel).mkdir(parents=True, exist_ok=True)
    (root / PATCH_PATH).write_text(patch_text, encoding='utf-8')
    receipt = (f'kernel_pin={EXPECTED_KERNEL_PIN}\n'
               f'patch_sha256={sha256(root / PATCH_PATH)}\n'
               'criterion_1_epdis_event_after_write=PASS\n'
               'criterion_2_zero_mmio_in_decisive_window=PASS\n'
               'criterion_3_programmed_split=PASS\nstandalone_apply_to_pin=PASS\n'
               'whitespace_error_all=PASS\ndiff_check=PASS\n'
               'criterion_4_campaign_composition=UNVERIFIED\n'
               'criterion_5_arm64_build=UNVERIFIED\n'
               'build_measurement_disabled=NOT_RUN\n'
               'build_measurement_enabled=NOT_RUN\n'
               'timing_perturbation_sensitivity=NOT_RUN\n')
    (root / RECEIPT_PATH).write_text(receipt, encoding='utf-8')
    verifier = ('verify_holder_contract_selftest.py\nholder_log_guard_selftest.py\n'
                'holder_roundtrip.py\nduplicate_census_selftest\n'
                "'duplicate_census:.'\nverify_status_sync_selftest.py\n"
                'closure_matrix_selftest\narchive_tracking_proof\n'
                'python3 verify_archive_tracking.py "$ROOT"\nstatus_sync_selftest\n'
                'python3 verify_status_sync.py\n')
    (root / VERIFIER_PATH).write_text(verifier, encoding='utf-8')
    for rel in ['tools/check_duplicates_full.py', 'DUPLICATES-OVERLAY.txt',
                'verify_archive_tracking.py', 'baseline/SHA256SUMS',
                'verify_status_sync.py', 'verify_status_sync_selftest.py']:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text('fixture\n', encoding='utf-8')
    (root / 'docs/PENDING.md').write_text(
        'real DWC2 gadget UDC\ng_dma=1\ng_dma_desc=0\nobserver ABI=9\n'
        'snapshot_atomic=1\nlost=0\nusbmon + device holder evidence\n'
        'UNMAP_DONE(iova,len,device)\nNO_REMAP(retired_range)\n'
        'post-unmap transaction/fault to retired range\n'
        'status        MIRROR_VERIFIED / ORIGINAL_PENDING\n'
        'does NOT       establish that Linux DWC2 carries the defect under study.\n'
        'Linux K_hw     UNDETERMINED\n', encoding='utf-8')
    (root / 'docs/IMPACT-ANALYSIS.md').write_text(
        'Does not move the evidence ladder.\n'
        'DMA is definitely still active when unmap occurs.\n'
        'That remains `UNKNOWN` and is the closure gate of this document.\n'
        '## 2. The closure gate (UNKNOWN)\n', encoding='utf-8')
    (root / 'STATUS.md').write_text(
        'R1A REAL DWC2 RUNTIME              NOT EXECUTED\n', encoding='utf-8')
    (root / 'docs/RUNTIME-STATE.txt').write_text(
        'runtime_execution=NOT_RUN\nhypothesis_result=UNDETERMINED\n', encoding='utf-8')
    (root / '.github/workflows/repository-gate.yml').write_text(
        'pull_request:\npush:\n  branches: [main]\n- run: ./VERIFY-REPOSITORY.sh\n',
        encoding='utf-8')
    (root / MATRIX_PATH).write_text(json.dumps(fixture_matrix(), indent=2) + '\n',
                                    encoding='utf-8')


def _rehash(root: Path) -> None:
    rp = root / RECEIPT_PATH
    rec = rp.read_text()
    old = next(l for l in rec.splitlines() if l.startswith('patch_sha256='))
    rp.write_text(rec.replace(old, 'patch_sha256=' + sha256(root / PATCH_PATH)))


def write_epoch(root: Path, **over) -> None:
    rec = {'epoch_id': 'E1', 'kernel_commit': EXPECTED_KERNEL_PIN,
           'kernel_build_id': 'bid', 'patch_sha256': sha256(root / PATCH_PATH),
           'config_sha256': 'c', 'device_harness_sha256': 'd',
           'host_harness_sha256': 'h', 'observer_contract': 'abi9', 'boot_id': 'b'}
    rec.update(over)
    (root / 'docs/RUN-EPOCH.txt').write_text(
        ''.join(f'{k}={v}\n' for k, v in rec.items()), encoding='utf-8')


def selftest() -> int:
    failures = 0
    ran = 0

    def expect(name, mutator, should_pass):
        nonlocal failures, ran
        ran += 1
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_fixture(root)
            mutator(root)
            errs = validate_matrix(root)
            ok = not errs
            if ok != should_pass:
                print(f'SELFTEST FAIL: {name}: expected {should_pass}, got {ok}',
                      file=sys.stderr)
                for e in errs:
                    print('  ' + e, file=sys.stderr)
                failures += 1

    expect('valid v2 fixture', lambda r: None, True)

    def v1_schema(r):
        p = r / MATRIX_PATH; d = json.loads(p.read_text())
        d['schema_version'] = 1; p.write_text(json.dumps(d))
    expect('v1 schema rejected', v1_schema, False)

    def v1_field(r):
        p = r / MATRIX_PATH; d = json.loads(p.read_text())
        d['dimensions'][0]['blocks_campaign'] = True; p.write_text(json.dumps(d))
    expect('v1 blocks_campaign field rejected', v1_field, False)

    def missing_dim(r):
        p = r / MATRIX_PATH; d = json.loads(p.read_text())
        d['dimensions'] = [x for x in d['dimensions'] if x['id'] != 'provenance']
        p.write_text(json.dumps(d))
    expect('missing required dimension rejected', missing_dim, False)

    def false_build_pass(r):
        p = r / MATRIX_PATH; d = json.loads(p.read_text())
        for x in d['dimensions']:
            if x['id'] == 'measurement_enabled_build':
                x['review_state'] = 'PASS'; x.pop('close_artifact', None)
        p.write_text(json.dumps(d))
    expect('NOT_RUN cannot be called PASS', false_build_pass, False)

    def patch_digest_mismatch(r):
        (r / PATCH_PATH).write_text((r / PATCH_PATH).read_text() + 'changed\n')
    expect('patch digest mismatch rejected', patch_digest_mismatch, False)

    # BUG 1 of v1: consumer closed on two empty files.
    def empty_consumer(r):
        (r / 'tools/validate_r1_lifetime_trace.py').write_text('')
        (r / 'tools/validate_r1_lifetime_trace_selftest.py').write_text('')
        v = r / VERIFIER_PATH
        v.write_text(v.read_text() + 'validate_r1_lifetime_trace.py\n'
                                     'validate_r1_lifetime_trace_selftest.py\n')
        p = r / MATRIX_PATH; d = json.loads(p.read_text())
        for x in d['dimensions']:
            if x['id'] == 'consumer_compatibility':
                x['review_state'] = 'PASS'; x.pop('close_artifact', None)
        p.write_text(json.dumps(d))
    expect('empty consumer cannot close the dimension', empty_consumer, False)

    # BUG 2 of v1: semantics preservation promoted by a receipt line alone.
    def receipt_only_semantics(r):
        rp = r / RECEIPT_PATH
        rp.write_text(rp.read_text() +
                      'criterion_6_functional_semantics_preservation=PASS\n')
        p = r / MATRIX_PATH; d = json.loads(p.read_text())
        for x in d['dimensions']:
            if x['id'] == 'functional_semantics_preservation':
                x['review_state'] = 'PASS'; x.pop('close_artifact', None)
        p.write_text(json.dumps(d))
    expect('receipt line alone cannot prove semantics', receipt_only_semantics, False)

    # BUG 3 of v1: a valid run had no PASS path.
    def valid_run_reaches_pass(r):
        (r / 'docs/RUNTIME-STATE.txt').write_text(
            'runtime_execution=VALID_RUN\nhypothesis_result=DISPROVEN\n')
        write_epoch(r)
        p = r / MATRIX_PATH
        d = fixture_matrix()
        p.write_text(json.dumps(d))
    expect('a declared VALID_RUN alone does not close the execution row',
           valid_run_reaches_pass, True)

    def invalid_run_is_fail(r):
        (r / 'docs/RUNTIME-STATE.txt').write_text(
            'runtime_execution=INVALID_RUN\nhypothesis_result=UNDETERMINED\n')
        write_epoch(r)
        p = r / MATRIX_PATH
        d = fixture_matrix({'runtime_execution': 'FAIL'})
        for x in d['dimensions']:
            if x['id'] == 'runtime_execution':
                x['blocker'] = 'invalid run'
        p.write_text(json.dumps(d))
    expect('an invalid run is a FAIL', invalid_run_is_fail, True)

    # Circularity guard.
    def runtime_blocks_run_readiness(r):
        p = r / MATRIX_PATH; d = json.loads(p.read_text())
        for x in d['dimensions']:
            if x['id'] == 'runtime_execution':
                x['blocks'] = 'run_readiness'
        p.write_text(json.dumps(d))
    expect('runtime_execution may not block run_readiness',
           runtime_blocks_run_readiness, False)

    # Structural, not token: move the event before the write.
    def event_before_write(r):
        bad = GOOD_PATCH.replace(
            '+\tdwc2_set_bit(hsotg, epctrl_reg, DXEPCTL_EPDIS | DXEPCTL_SNAK);\n'
            '+\tdwc2_r1_measure_event(DWC2_R1_EPDIS_WRITTEN);\n',
            '+\tdwc2_r1_measure_event(DWC2_R1_EPDIS_WRITTEN);\n'
            '+\tdwc2_set_bit(hsotg, epctrl_reg, DXEPCTL_EPDIS | DXEPCTL_SNAK);\n')
        (r / PATCH_PATH).write_text(bad); _rehash(r)
    expect('event emitted before the write is rejected', event_before_write, False)

    # Structural: MMIO outside the DIAG guard.
    def mmio_unguarded(r):
        bad = GOOD_PATCH.replace('+#ifdef CONFIG_USB_DWC2_R1_MEASURE_DIAG\n', '')
        (r / PATCH_PATH).write_text(bad); _rehash(r)
    expect('unguarded diagnostic MMIO is rejected', mmio_unguarded, False)

    def lose_diag_identity(r):
        bad = GOOD_PATCH.replace('+#define DWC2_R1_FLAG_DIAG_BUILD BIT(7)\n', '')
        (r / PATCH_PATH).write_text(bad); _rehash(r)
    expect('diagnostic/decisive indistinguishability rejected', lose_diag_identity, False)

    def lose_meta_wiring(r):
        p = r / VERIFIER_PATH
        p.write_text(p.read_text().replace('closure_matrix_selftest', ''))
    expect('missing meta-selftest wiring rejected', lose_meta_wiring, False)

    def open_without_close(r):
        p = r / MATRIX_PATH; d = json.loads(p.read_text())
        for x in d['dimensions']:
            if x['id'] == 'campaign_composition':
                x.pop('close_artifact', None)
        p.write_text(json.dumps(d))
    expect('open item requires closure artifact', open_without_close, False)

    def ready_with_open(r):
        p = r / MATRIX_PATH; d = json.loads(p.read_text())
        d['run_readiness'] = 'READY'; p.write_text(json.dumps(d))
    expect('run cannot be ready with open blockers', ready_with_open, False)

    def weaken_external(r):
        p = r / 'docs/PENDING.md'
        p.write_text(p.read_text().replace(
            'does NOT       establish that Linux DWC2 carries the defect under study.\n', ''))
    expect('external overclaim boundary enforced', weaken_external, False)

    def weaken_impact(r):
        p = r / 'docs/IMPACT-ANALYSIS.md'
        p.write_text(p.read_text().replace(
            'That remains `UNKNOWN` and is the closure gate of this document.\n', ''))
    expect('impact unknown boundary enforced', weaken_impact, False)

    def missing_source(r):
        p = r / MATRIX_PATH; d = json.loads(p.read_text())
        d['dimensions'][0]['sources'] = ['missing.file']; p.write_text(json.dumps(d))
    expect('declared source must exist', missing_source, False)

    def bad_runtime_token(r):
        (r / 'docs/RUNTIME-STATE.txt').write_text(
            'runtime_execution=MAYBE\nhypothesis_result=UNDETERMINED\n')
    expect('unknown runtime state token rejected', bad_runtime_token, False)

    def demote_blocks(r):
        p = r / MATRIX_PATH; d = json.loads(p.read_text())
        for x in d['dimensions']:
            if x['id'] == 'measurement_enabled_build':
                x['blocks'] = 'none'
        p.write_text(json.dumps(d))
    expect('a blocker cannot be demoted to none', demote_blocks, False)

    def evidence_ready_over_blocked_run(r):
        p = r / MATRIX_PATH
        d = fixture_matrix({k: 'PASS' for k in EXPECTED_BLOCKS
                            if EXPECTED_BLOCKS[k] == 'evidence_admissibility'})
        d['evidence_admissibility'] = 'READY'
        p.write_text(json.dumps(d))
    expect('evidence cannot be ready while the run is blocked',
           evidence_ready_over_blocked_run, False)

    def proven_without_run(r):
        (r / 'docs/RUNTIME-STATE.txt').write_text(
            'runtime_execution=NOT_RUN\nhypothesis_result=PROVEN\n')
    expect('PROVEN without a valid run is rejected', proven_without_run, False)

    def epoch_wrong_patch(r):
        (r / 'docs/RUNTIME-STATE.txt').write_text(
            'runtime_execution=VALID_RUN\nhypothesis_result=UNDETERMINED\n')
        write_epoch(r, patch_sha256='deadbeef')
    expect('run epoch bound to a different patch is rejected', epoch_wrong_patch, False)

    def mmio_partial_guard(r):
        bad = GOOD_PATCH.replace(
            '+\t\tepsiz = dwc2_readl(hsotg, DOEPTSIZ(hs_ep->index));\n', '')
        bad = bad.replace('+#endif\n',
                          '+#endif\n+\t\tepsiz = dwc2_readl(hsotg, DOEPTSIZ(hs_ep->index));\n')
        (r / PATCH_PATH).write_text(bad); _rehash(r)
    expect('one snapshot register left outside the guard is rejected',
           mmio_partial_guard, False)

    def arm_order_by_enum_only(r):
        bad = GOOD_PATCH.replace(
            '+\t\t\tdwc2_writel(hsotg, ureq->dma, dma_reg);\n'
            '+\t\t\tdwc2_r1_measure_dma_addr_written(hsotg, hs_ep, hs_req, ureq->dma);\n',
            '+\tDWC2_R1_DMA_ADDR_WRITTEN = 2,\n')
        (r / PATCH_PATH).write_text(bad); _rehash(r)
    expect('enum declaration order does not satisfy the call-site predicate',
           arm_order_by_enum_only, False)

    def lineage_named_not_assigned(r):
        bad = GOOD_PATCH.replace('+\ths_req->r1_map_id = 1;\n', '+\tr1_map_id\n')
        (r / PATCH_PATH).write_text(bad); _rehash(r)
    expect('lineage named but never assigned is rejected',
           lineage_named_not_assigned, False)

    def declaration_only_cannot_pass(r):
        p = r / MATRIX_PATH; d = json.loads(p.read_text())
        for x in d['dimensions']:
            if x['id'] == 'standalone_apply':
                x['review_state'] = 'PASS'; x.pop('close_artifact', None)
        p.write_text(json.dumps(d))
    expect('a declaration-only row may not read PASS',
           declaration_only_cannot_pass, False)

    def swapping_the_result_word_changes_nothing(r):
        write_epoch(r)
        (r / 'docs/RUNTIME-STATE.txt').write_text(
            'runtime_execution=VALID_RUN\nhypothesis_result=PROVEN\n')
        p = r / MATRIX_PATH
        d = fixture_matrix()
        p.write_text(json.dumps(d))
    expect('PROVEN in a text file does not close the result row',
           swapping_the_result_word_changes_nothing, True)

    def epoch_placeholders_do_not_pass(r):
        write_epoch(r)
        (r / 'docs/RUNTIME-STATE.txt').write_text(
            'runtime_execution=VALID_RUN\nhypothesis_result=UNDETERMINED\n')
        p = r / MATRIX_PATH; d = json.loads(p.read_text())
        for x in d['dimensions']:
            if x['id'] == 'run_epoch_binding':
                x['review_state'] = 'PASS'; x.pop('close_artifact', None)
            if x['id'] == 'runtime_execution':
                x['review_state'] = 'PASS'; x.pop('close_artifact', None)
        p.write_text(json.dumps(d))
    expect('partially bound epoch fields may not read PASS',
           epoch_placeholders_do_not_pass, False)

    # v4 wrote `derivation` into the matrix and never read it back.
    def derivation_relabelled(r):
        p = r / MATRIX_PATH; d = json.loads(p.read_text())
        for x in d['dimensions']:
            if x['id'] == 'standalone_apply':
                x['derivation'] = 'structural_predicate'
        p.write_text(json.dumps(d))
    expect('a row may not relabel its own derivation kind',
           derivation_relabelled, False)

    def derivation_absent(r):
        p = r / MATRIX_PATH; d = json.loads(p.read_text())
        for x in d['dimensions']:
            if x['id'] == 'measurement_enabled_build':
                x.pop('derivation', None)
        p.write_text(json.dumps(d))
    expect('a row must declare a derivation kind', derivation_absent, False)

    # The clamp is a property of the COMPUTED layer, so it is tested there.
    # Routing this through validate_matrix() would not have measured it: the
    # matrix-layer check already rejects a DECLARATION_ONLY row that declares
    # PASS, so a fixture that edits both the receipt and the matrix fails with
    # or without the clamp and discriminates nothing. The question the clamp
    # answers is narrower and is asked directly - can a receipt word alone make
    # compute_states() read PASS for a row whose PASS rests on a declaration.
    def expect_computed(name, mutator, ident, want_state, want_defect):
        nonlocal failures, ran
        ran += 1
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_fixture(root)
            mutator(root)
            states, errs = compute_states(root)
            got = states.get(ident)
            defect = any(f'{ident}: uncorroborated PASS' in e for e in errs)
            if got != want_state or defect != want_defect:
                print(f'SELFTEST FAIL: {name}: expected {want_state}/'
                      f'defect={want_defect}, got {got}/defect={defect}',
                      file=sys.stderr)
                failures += 1

    def receipt_says(value):
        def m(r):
            rp = r / RECEIPT_PATH
            rp.write_text(rp.read_text().replace(
                'build_measurement_enabled=NOT_RUN',
                f'build_measurement_enabled={value}'))
        return m

    expect_computed('a receipt word alone may not compute PASS for a '
                    'declaration-only build row',
                    receipt_says('PASS'), 'measurement_enabled_build',
                    'OPEN', True)

    # The other half of the asymmetry, and the guard against an over-broad
    # clamp: an unverified success is demoted, an unverified failure stands.
    expect_computed('a declared build failure is still a FAIL, not clamped',
                    receipt_says('FAILED'), 'measurement_enabled_build',
                    'FAIL', False)

    # The clamp must not move rows that earned their PASS.
    expect_computed('a derived row keeps its PASS under the clamp',
                    lambda r: None, 'event_ordering', 'PASS', False)

    def unknown_derivation_kind(r):
        p = r / MATRIX_PATH; d = json.loads(p.read_text())
        d['dimensions'].append({'id': 'source_pin', 'review_state': 'PASS',
                                'evidence_state': 'dup', 'blocks': 'none',
                                'sources': ['STATUS.md']})
        p.write_text(json.dumps(d))
    expect('duplicate dimension rejected', unknown_derivation_kind, False)

    if failures:
        print(f'CLOSURE_MATRIX_SELFTEST: FAIL ({failures})', file=sys.stderr)
        return 1
    # Derived, not typed. v2 printed 20/20 while running 21 controls, which is
    # the same "a number that says so" failure this contract exists to prevent.
    print(f'CLOSURE_MATRIX_SELFTEST: PASS ({ran}/{ran} controls)')
    return 0


def main(argv) -> int:
    if len(argv) > 1 and argv[1] == 'selftest':
        return selftest()
    root = Path(argv[1]).resolve() if len(argv) > 1 else Path(__file__).resolve().parent.parent
    return run(root)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
