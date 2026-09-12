#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
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
    'behavior_preservation', 'event_ordering', 'observer_nonperturbation',
    'mapping_lineage_design', 'consumer_compatibility', 'negative_controls',
    'cross_tree_duplicate_census', 'provenance', 'documentation_sync',
    'runtime_requirements', 'runtime_execution', 'external_evidence_boundary',
    'impact_claim_boundary', 'continuous_enforcement',
)
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
    states['standalone_apply'] = 'PASS' if all(
        receipt.get(k) == 'PASS' for k in
        ('standalone_apply_to_pin', 'whitespace_error_all', 'diff_check')) else 'FAIL'
    states['measurement_disabled_build'] = state_from_receipt(receipt.get('build_measurement_disabled'))
    states['measurement_enabled_build'] = state_from_receipt(receipt.get('build_measurement_enabled'))
    states['target_arm64_build'] = state_from_receipt(receipt.get('criterion_5_arm64_build'))
    states['campaign_composition'] = state_from_receipt(receipt.get('criterion_4_campaign_composition'))
    states['behavior_preservation'] = state_from_receipt(receipt.get('criterion_6_behavior_preservation'))

    states['event_ordering'] = 'PASS' if (
        all_tokens(receipt_text, ['criterion_1_epdis_event_after_write=PASS',
                                  'criterion_3_programmed_split=PASS']) and
        all_tokens(patch, ['DWC2_R1_EPDIS_WRITTEN', 'DWC2_R1_DMA_ADDR_WRITTEN',
                           'DWC2_R1_EP_ARMED']) and
        'DWC2_R1_EPDIS_ASSERT' not in patch) else 'FAIL'

    states['observer_nonperturbation'] = 'PASS' if (
        all_tokens(receipt_text, ['criterion_2_zero_mmio_in_decisive_window=PASS']) and
        all_tokens(patch, ['config USB_DWC2_R1_MEASURE_DIAG', 'default n',
                           'DWC2_R1_FLAG_DIAG_BUILD BIT(7)', 'A NEGATIVE result does',
                           'Say N for the campaign build.'])) else 'FAIL'

    states['mapping_lineage_design'] = 'PASS' if all_tokens(patch, [
        'r1_req_id', 'r1_map_id', 'r1_dma', 'DWC2_R1_MAP',
        'DWC2_R1_DMA_ADDR_WRITTEN', 'DWC2_R1_UNMAP_BEGIN', 'DWC2_R1_UNMAP_DONE']) else 'FAIL'

    consumer = root / 'tools/validate_r1_lifetime_trace.py'
    consumer_test = root / 'tools/validate_r1_lifetime_trace_selftest.py'
    states['consumer_compatibility'] = 'PASS' if (
        consumer.is_file() and consumer_test.is_file() and
        all_tokens(verifier, ['validate_r1_lifetime_trace_selftest.py',
                              'validate_r1_lifetime_trace.py'])) else 'OPEN'

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

    status_path = root / 'STATUS.md'
    states['runtime_execution'] = 'OPEN' if (
        status_path.is_file() and
        'R1A REAL DWC2 RUNTIME              NOT EXECUTED' in
        status_path.read_text(encoding='utf-8')) else 'FAIL'

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

    states['continuous_enforcement'] = 'OPEN'
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

    if data.get('schema_version') != 1:
        errors.append(f"schema_version must be 1, got {data.get('schema_version')!r}")
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
        if not isinstance(dim.get('blocks_campaign'), bool):
            errors.append(f'{ident}: blocks_campaign must be boolean')
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
        if declared == 'OPEN' and not (isinstance(dim.get('close_artifact'), str) and dim['close_artifact'].strip()):
            errors.append(f'{ident}: OPEN requires close_artifact')
        if declared == 'FAIL' and not (isinstance(dim.get('blocker'), str) and dim['blocker'].strip()):
            errors.append(f'{ident}: FAIL requires blocker')

    computed_campaign = 'BLOCKED'
    if by_id and all(by_id[d].get('review_state') == 'PASS'
                     for d in REQUIRED_DIMENSIONS
                     if by_id.get(d, {}).get('blocks_campaign') is True):
        computed_campaign = 'READY'
    declared_campaign = data.get('campaign_admissibility')
    if declared_campaign not in ALLOWED_CAMPAIGN:
        errors.append(f'invalid campaign_admissibility {declared_campaign!r}')
    elif declared_campaign != computed_campaign:
        errors.append(f'campaign_admissibility: matrix says {declared_campaign}, computed {computed_campaign}')
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
    print(f"  campaign_admissibility   {data['campaign_admissibility']}")
    print('  open_dimensions          ' + (', '.join(open_dims) if open_dims else 'none'))
    return 0


def fixture_matrix() -> dict:
    states = {
        'source_pin': 'PASS', 'standalone_apply': 'PASS',
        'measurement_disabled_build': 'OPEN', 'measurement_enabled_build': 'OPEN',
        'target_arm64_build': 'OPEN', 'campaign_composition': 'OPEN',
        'behavior_preservation': 'OPEN', 'event_ordering': 'PASS',
        'observer_nonperturbation': 'PASS', 'mapping_lineage_design': 'PASS',
        'consumer_compatibility': 'OPEN', 'negative_controls': 'PASS',
        'cross_tree_duplicate_census': 'PASS', 'provenance': 'PASS',
        'documentation_sync': 'PASS', 'runtime_requirements': 'PASS',
        'runtime_execution': 'OPEN', 'external_evidence_boundary': 'PASS',
        'impact_claim_boundary': 'PASS', 'continuous_enforcement': 'OPEN',
    }
    dims = []
    for ident in REQUIRED_DIMENSIONS:
        state = states[ident]
        dim = {'id': ident, 'review_state': state, 'evidence_state': 'fixture',
               'blocks_campaign': ident in {
                   'measurement_disabled_build', 'measurement_enabled_build',
                   'target_arm64_build', 'campaign_composition',
                   'behavior_preservation', 'consumer_compatibility',
                   'runtime_execution'},
               'sources': ['STATUS.md']}
        if state == 'OPEN':
            dim['close_artifact'] = 'fixture close artifact'
        if state == 'FAIL':
            dim['blocker'] = 'fixture blocker'
        dims.append(dim)
    return {'schema_version': 1, 'contract_id': 'fixture-v1',
            'campaign_admissibility': 'BLOCKED', 'dimensions': dims}


def write_fixture(root: Path) -> None:
    for rel in ['docs', 'r1a-device/instrumentation', 'tools', 'baseline', '.github/workflows']:
        (root / rel).mkdir(parents=True, exist_ok=True)
    patch = ('config USB_DWC2_R1_MEASURE_DIAG\n+\tdefault n\n+A NEGATIVE result does\n'
             '+Say N for the campaign build.\n+#define DWC2_R1_FLAG_DIAG_BUILD BIT(7)\n'
             '+DWC2_R1_EPDIS_WRITTEN\n+DWC2_R1_DMA_ADDR_WRITTEN\n+DWC2_R1_EP_ARMED\n'
             '+r1_req_id r1_map_id r1_dma DWC2_R1_MAP DWC2_R1_UNMAP_BEGIN DWC2_R1_UNMAP_DONE\n')
    (root / PATCH_PATH).write_text(patch, encoding='utf-8')
    receipt = (f'kernel_pin={EXPECTED_KERNEL_PIN}\npatch_sha256={sha256(root / PATCH_PATH)}\n'
               'criterion_1_epdis_event_after_write=PASS\n'
               'criterion_2_zero_mmio_in_decisive_window=PASS\n'
               'criterion_3_programmed_split=PASS\nstandalone_apply_to_pin=PASS\n'
               'whitespace_error_all=PASS\ndiff_check=PASS\n'
               'criterion_4_campaign_composition=UNVERIFIED\ncriterion_5_arm64_build=UNVERIFIED\n'
               'build_measurement_disabled=NOT_RUN\nbuild_measurement_enabled=NOT_RUN\n')
    (root / RECEIPT_PATH).write_text(receipt, encoding='utf-8')
    verifier = ('verify_holder_contract_selftest.py\nholder_log_guard_selftest.py\n'
                'holder_roundtrip.py\nduplicate_census_selftest\n\'duplicate_census:.\'\n'
                'verify_status_sync_selftest.py\nclosure_matrix_selftest\narchive_tracking_proof\n'
                'python3 verify_archive_tracking.py "$ROOT"\nstatus_sync_selftest\n'
                'python3 verify_status_sync.py\n')
    (root / VERIFIER_PATH).write_text(verifier, encoding='utf-8')
    for rel in ['tools/check_duplicates_full.py', 'DUPLICATES-OVERLAY.txt',
                'verify_archive_tracking.py', 'baseline/SHA256SUMS',
                'verify_status_sync.py', 'verify_status_sync_selftest.py']:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text('fixture\n', encoding='utf-8')
    pending = ('real DWC2 gadget UDC\ng_dma=1\ng_dma_desc=0\nobserver ABI=9\n'
               'snapshot_atomic=1\nlost=0\nusbmon + device holder evidence\n'
               'UNMAP_DONE(iova,len,device)\nNO_REMAP(retired_range)\n'
               'post-unmap transaction/fault to retired range\n'
               'status        MIRROR_VERIFIED / ORIGINAL_PENDING\n'
               'does NOT       establish that Linux DWC2 carries the defect under study.\n'
               'Linux K_hw     UNDETERMINED\n')
    (root / 'docs/PENDING.md').write_text(pending, encoding='utf-8')
    impact = ('Does not move the evidence ladder.\n'
              'DMA is definitely still active when unmap occurs.\n'
              'That remains `UNKNOWN` and is the closure gate of this document.\n'
              '## 2. The closure gate (UNKNOWN)\n')
    (root / 'docs/IMPACT-ANALYSIS.md').write_text(impact, encoding='utf-8')
    (root / 'STATUS.md').write_text('R1A REAL DWC2 RUNTIME              NOT EXECUTED\n', encoding='utf-8')
    (root / '.github/workflows/repository-gate.yml').write_text(
        'pull_request:\npush:\n  branches: [main]\n- run: ./VERIFY-REPOSITORY.sh\n', encoding='utf-8')
    (root / MATRIX_PATH).write_text(json.dumps(fixture_matrix(), indent=2) + '\n', encoding='utf-8')


def selftest() -> int:
    failures = 0

    def expect(name, mutator, should_pass):
        nonlocal failures
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_fixture(root)
            mutator(root)
            ok = not validate_matrix(root)
            if ok != should_pass:
                print(f'SELFTEST FAIL: {name}: expected {should_pass}, got {ok}', file=sys.stderr)
                for e in validate_matrix(root):
                    print('  ' + e, file=sys.stderr)
                failures += 1

    expect('valid fixture', lambda r: None, True)

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

    def stale_open_after_pass(r):
        rp = r / RECEIPT_PATH
        rp.write_text(rp.read_text().replace('build_measurement_enabled=NOT_RUN',
                                             'build_measurement_enabled=PASS'))
    expect('matrix stale when open item closes', stale_open_after_pass, False)

    def patch_digest_mismatch(r):
        (r / PATCH_PATH).write_text((r / PATCH_PATH).read_text() + 'changed\n')
    expect('patch digest mismatch rejected', patch_digest_mismatch, False)

    def lose_diag_identity(r):
        p = r / PATCH_PATH
        p.write_text(p.read_text().replace('#define DWC2_R1_FLAG_DIAG_BUILD BIT(7)', ''))
        rp = r / RECEIPT_PATH; rec = rp.read_text()
        rec = rec.replace(next(l for l in rec.splitlines() if l.startswith('patch_sha256=')),
                          'patch_sha256=' + sha256(p))
        rp.write_text(rec)
    expect('diagnostic/decisive indistinguishability rejected', lose_diag_identity, False)

    def lose_negative_control_wiring(r):
        p = r / VERIFIER_PATH
        p.write_text(p.read_text().replace('closure_matrix_selftest', ''))
    expect('missing meta-selftest wiring rejected', lose_negative_control_wiring, False)

    def open_without_close(r):
        p = r / MATRIX_PATH; d = json.loads(p.read_text())
        for x in d['dimensions']:
            if x['id'] == 'consumer_compatibility':
                x.pop('close_artifact', None)
        p.write_text(json.dumps(d))
    expect('open item requires closure artifact', open_without_close, False)

    def campaign_ready_with_open(r):
        p = r / MATRIX_PATH; d = json.loads(p.read_text())
        d['campaign_admissibility'] = 'READY'; p.write_text(json.dumps(d))
    expect('campaign cannot be ready with open blockers', campaign_ready_with_open, False)

    def consumer_closes_but_matrix_stale(r):
        (r / 'tools/validate_r1_lifetime_trace.py').write_text('x')
        (r / 'tools/validate_r1_lifetime_trace_selftest.py').write_text('x')
        p = r / VERIFIER_PATH
        p.write_text(p.read_text() + '\nvalidate_r1_lifetime_trace.py\nvalidate_r1_lifetime_trace_selftest.py\n')
    expect('closed consumer gap forces matrix update', consumer_closes_but_matrix_stale, False)

    def weaken_external_boundary(r):
        p = r / 'docs/PENDING.md'
        p.write_text(p.read_text().replace(
            'does NOT       establish that Linux DWC2 carries the defect under study.\n', ''))
    expect('external corroboration overclaim boundary enforced', weaken_external_boundary, False)

    def weaken_impact_boundary(r):
        p = r / 'docs/IMPACT-ANALYSIS.md'
        p.write_text(p.read_text().replace(
            'That remains `UNKNOWN` and is the closure gate of this document.\n', ''))
    expect('impact unknown boundary enforced', weaken_impact_boundary, False)

    def missing_source(r):
        p = r / MATRIX_PATH; d = json.loads(p.read_text())
        d['dimensions'][0]['sources'] = ['missing.file']; p.write_text(json.dumps(d))
    expect('declared source must exist', missing_source, False)

    if failures:
        print(f'CLOSURE_MATRIX_SELFTEST: FAIL ({failures})', file=sys.stderr)
        return 1
    print('CLOSURE_MATRIX_SELFTEST: PASS (12/12 controls)')
    return 0


def main(argv) -> int:
    if len(argv) > 1 and argv[1] == 'selftest':
        return selftest()
    root = Path(argv[1]).resolve() if len(argv) > 1 else Path(__file__).resolve().parent.parent
    return run(root)


if __name__ == '__main__':
    raise SystemExit(main(sys.argv))
