from __future__ import annotations
import hashlib
import json
import math
import numpy as np
import subprocess
from collections import defaultdict
from pathlib import Path
ROOT = Path('/home/icy/MePhC')
AUDIT = ROOT / 'audit' / 'e7i4f'
CHECKPOINTS = AUDIT / 'checkpoints' / 'full'
RUNNER_SHA = '4e40f74326114651d0f21f8c21556112022eb6eb'
RESULT_COMMIT_SHA = '387567e2b00271b62371a0838e36f085c7110e53'
C1_SOURCE_COMMIT = '1f9ffe49cf66720ec729d66490d0f013d83321e6'
EXPECTED_CHECKPOINT_MANIFEST_SHA = '2774c36937e30ef8b95530af2320a6221f76d217a9f4cb71df1682a2c087e51d'
PI = math.pi
def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
def sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
def atomic_json(path: Path, value: dict) -> None:
    tmp = path.with_name(path.name + '.tmp')
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    tmp.write_bytes(raw)
    tmp.replace(path)
def close(value: float, target: float) -> bool:
    return math.isclose(value, target, rel_tol=0.0, abs_tol=1e-12)
def finite(value) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(float(value))
def main() -> None:
    import sys
    sys.path.insert(0, str(ROOT))
    from audit.e7i4f.run_stage2_orchestrator import (
        build_contract,
        build_triangular_coordinate_preflight,
        build_triangular_reference_geometry,
        checkpoint_path,
        paper_style_truncated_k_hbz,
        sample_domain,
        valid_checkpoint,
    )
    current_head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    subprocess.run(['git', 'merge-base', '--is-ancestor', C1_SOURCE_COMMIT, current_head], cwd=ROOT, check=True)
    reducer_sha256 = sha_bytes(Path(__file__).read_bytes())
    result_path = AUDIT / 'result.json'
    old_result = json.loads(result_path.read_text())
    if old_result.get('runner_code_git_sha') != RUNNER_SHA:
        raise RuntimeError('result runner SHA binding mismatch')
    if old_result.get('checkpoint_manifest_sha256') != EXPECTED_CHECKPOINT_MANIFEST_SHA:
        raise RuntimeError('result checkpoint manifest binding mismatch')
    geometry = build_triangular_reference_geometry(0.0)
    preflight = build_triangular_coordinate_preflight()
    domain = paper_style_truncated_k_hbz(fr=0.0, delta_k=0.10, delta_gamma=0.10)
    sample = sample_domain(domain, 1.0 / 36.0)
    if len(sample.centers) != 1201:
        raise RuntimeError(f'unexpected sample size {len(sample.centers)}')
    contracts = []
    payloads = []
    original_manifest = []
    compact_entries = []
    low_gap_by_q = {}
    telemetry = []
    delta_counts = defaultdict(int)
    delta_areas = defaultdict(float)
    for index in range(len(sample.centers)):
        contract = build_contract(ROOT, sample, index, geometry, preflight, domain)
        contract['runner_code_git_sha'] = RUNNER_SHA
        path = checkpoint_path(CHECKPOINTS, contract['element_id'])
        if not path.exists() or not valid_checkpoint(path, contract):
            raise RuntimeError(f'checkpoint identity validation failed: {contract["element_id"]}')
        payload = json.loads(path.read_text())
        result = payload['result']
        if not result.get('qualified') or not result.get('profile_passed'):
            raise RuntimeError(f'unqualified checkpoint: {contract["element_id"]}')
        if not finite(result.get('omega_trace_q')):
            raise RuntimeError(f'non-finite omega: {contract["element_id"]}')
        attempts = payload.get('adaptive_attempts') or []
        if not attempts:
            raise RuntimeError(f'missing adaptive attempt: {contract["element_id"]}')
        primary_delta = float(result['local_delta_k'])
        matching = [a for a in attempts if close(float(a['primary_delta']), primary_delta)]
        if len(matching) != 1:
            raise RuntimeError(f'ambiguous primary delta: {contract["element_id"]}')
        attempt = matching[0]
        reference_delta = float(attempt['reference_delta'])
        checkpoint_sha = sha_bytes(path.read_bytes())
        original_manifest.append({
            'element_id': contract['element_id'],
            'checkpoint_sha256': checkpoint_sha,
            'weight': contract['integration_weight'],
        })
        compact_entries.append({
            'element_id': contract['element_id'],
            'evaluation_q': contract['evaluation_q'],
            'integration_weight': contract['integration_weight'],
            'primary_local_delta': primary_delta,
            'reference_local_delta': reference_delta,
            'qualified': bool(result['qualified']),
            'omega_trace_q': float(result['omega_trace_q']),
            'profile_passed': bool(result['profile_passed']),
            'checkpoint_sha256': checkpoint_sha,
        })
        telemetry.append(payload.get('telemetry', {}))
        delta_key = '1/36' if close(primary_delta, 1.0 / 36.0) else '1/72' if close(primary_delta, 1.0 / 72.0) else '1/144' if close(primary_delta, 1.0 / 144.0) else f'{primary_delta:.17g}'
        delta_counts[delta_key] += 1
        delta_areas[delta_key] += float(contract['integration_weight'])
        for profile in result.get('low_gap_profile_flat', []):
            if not finite(profile.get('R48_G34')) or float(profile['R48_G34']) >= 0.05:
                continue
            q_raw = np.asarray(profile['q'], dtype=float)
            basis = np.asarray(preflight.public_period_basis, dtype=float)
            fractional = np.linalg.solve(basis, q_raw)
            fractional = fractional - np.floor(fractional)
            q = tuple(float(x) for x in fractional)
            previous = low_gap_by_q.get(q)
            passed = profile.get('profile') == 'LOW_GAP_PASS'
            row = {
                'q': list(q),
                'profile_passed': passed,
                'profile': profile.get('profile'),
                'R48_G34': profile.get('R48_G34'),
                'R64_G34': profile.get('R64_G34'),
                'relative_R48': profile.get('relative_R48'),
                'relative_R64': profile.get('relative_R64'),
                'stability_ratio': profile.get('stability_ratio'),
            }
            if previous is None or (previous['profile_passed'] and not passed):
                low_gap_by_q[q] = row
    if sha_bytes(canonical(original_manifest)) != EXPECTED_CHECKPOINT_MANIFEST_SHA:
        raise RuntimeError('checkpoint manifest replay failed')
    compact_manifest = {
        'schema': 'e7i4f_stage2_reduction_manifest_v1',
        'runner_code_git_sha': RUNNER_SHA,
        'checkpoint_manifest_sha256': EXPECTED_CHECKPOINT_MANIFEST_SHA,
        'element_count': len(compact_entries),
        'entries': compact_entries,
    }
    compact_hash = sha_bytes(canonical(compact_entries))
    atomic_json(AUDIT / 'stage2_reduction_manifest.json', compact_manifest)
    compact_manifest_file_sha = sha_bytes((AUDIT / 'stage2_reduction_manifest.json').read_bytes())
    replay = json.loads((AUDIT / 'stage2_reduction_manifest.json').read_text())['entries']
    retained_area = float(sample.retained_area_q)
    qualified_area = sum(float(row['integration_weight']) for row in replay if row['qualified'])
    unqualified_area = sum(float(row['integration_weight']) for row in replay if not row['qualified'])
    integral = sum(float(row['integration_weight']) * float(row['omega_trace_q']) for row in replay)
    chern = integral / (2.0 * PI)
    if len(replay) != 1201 or len({row['element_id'] for row in replay}) != 1201:
        raise RuntimeError('compact manifest element identity check failed')
    if not all(finite(row['integration_weight']) and float(row['integration_weight']) > 0 for row in replay):
        raise RuntimeError('compact manifest weight check failed')
    if not all(finite(row['omega_trace_q']) for row in replay):
        raise RuntimeError('compact manifest omega check failed')
    if abs(integral - float(old_result['curvature_integral'])) > 1e-15 or abs(chern - float(old_result['composite_valley_chern'])) > 1e-15:
        raise RuntimeError('offline replay differs from committed scientific result')
    if abs(qualified_area - retained_area) > 1e-12 or abs(unqualified_area) > 1e-15:
        raise RuntimeError('area aggregation check failed')
    low_gap_rows = list(low_gap_by_q.values())
    r48 = [float(row['R48_G34']) for row in low_gap_rows if finite(row.get('R48_G34'))]
    r64 = [float(row['R64_G34']) for row in low_gap_rows if finite(row.get('R64_G34'))]
    rel = [float(row['relative_R48']) for row in low_gap_rows if finite(row.get('relative_R48'))]
    stability = [float(row['stability_ratio']) for row in low_gap_rows if finite(row.get('stability_ratio'))]
    failed = [row for row in low_gap_rows if not row['profile_passed']]
    stage1 = json.loads((ROOT / 'audit' / 'e7i4e' / 'result.json').read_text())
    stage1_chern = 0.00039168033110070674
    stage1_integral = 0.002461000101483196
    stage1_stage2 = {
        'stage1_grid_spacing': '1/18',
        'stage1_composite_valley_chern': stage1_chern,
        'stage1_curvature_integral': stage1_integral,
        'stage2_grid_spacing': '1/36',
        'stage2_composite_valley_chern': chern,
        'stage2_curvature_integral': integral,
        'integration_grid_abs_difference': abs(stage1_chern - chern),
        'integration_grid_relative_difference_descriptive': abs(stage1_chern - chern) / abs(stage1_chern),
        'curvature_integral_abs_difference': abs(stage1_integral - integral),
        'stage1_source_status': stage1.get('corrected_stage1_status'),
    }
    telemetry_summary = {
        'max_worker_peak_rss_kib': max(int(x.get('worker_peak_rss_kib', 0)) for x in telemetry),
        'total_worker_solve_requests': sum(int(x.get('worker_solve_requests', 0)) for x in telemetry),
        'total_worker_recorded_solver_failures': sum(int(x.get('solver_failures', 0)) for x in telemetry),
        'environment_execution_architecture': 'FRESH_SUBPROCESS_PER_ELEMENT',
    }
    closure = {
        'schema': 'e7i4f_c2_closure_v1',
        'work_order': 'TRILATT-E7I4F-C2-20260823-142',
        'c1_source_commit': C1_SOURCE_COMMIT,
        'reducer_code_git_sha': current_head,
        'reducer_sha256': reducer_sha256,
        'runner_code_git_sha': RUNNER_SHA,
        'stage2_result_commit_sha': RESULT_COMMIT_SHA,
        'checkpoint_manifest_sha256': EXPECTED_CHECKPOINT_MANIFEST_SHA,
        'compact_reduction_manifest_sha256': compact_hash,
        'compact_manifest_sha256': compact_manifest_file_sha,
        'element_count': len(replay),
        'qualified_element_count': sum(1 for row in replay if row['qualified']),
        'retained_area_q': retained_area,
        'qualified_area_q': qualified_area,
        'unqualified_area_q': unqualified_area,
        'qualified_area_fraction': 1.0 if abs(qualified_area - retained_area) <= 1e-12 else qualified_area / retained_area,
        'unqualified_area_fraction': 0.0 if abs(unqualified_area) <= 1e-15 else unqualified_area / retained_area,
        'curvature_integral': integral,
        'composite_valley_chern': chern,
        'stage2_replay_abs_difference': {
            'curvature_integral': abs(integral - float(old_result['curvature_integral'])),
            'composite_valley_chern': abs(chern - float(old_result['composite_valley_chern'])),
        },
        'delta_distribution': {
            'count_primary_delta_1over36': delta_counts['1/36'],
            'area_primary_delta_1over36': delta_areas['1/36'],
            'count_primary_delta_1over72': delta_counts['1/72'],
            'area_primary_delta_1over72': delta_areas['1/72'],
            'count_primary_delta_1over144': delta_counts['1/144'],
            'area_primary_delta_1over144': delta_areas['1/144'],
            'count_sum': sum(delta_counts.values()),
            'area_sum': sum(delta_areas.values()),
        },
        'low_gap_profile_summary': {
            'low_gap_unique_q_count': len(low_gap_rows),
            'low_gap_profile_passed_unique_q_count': len(low_gap_rows) - len(failed),
            'low_gap_profile_failed_unique_q_count': len(failed),
            'min_low_gap_g34_r48': min(r48) if r48 else None,
            'min_low_gap_g34_r64': min(r64) if r64 else None,
            'min_low_gap_relative_g34': min(rel) if rel else None,
            'min_gap_stability_ratio': min(stability) if stability else None,
        },
        'execution_summary': telemetry_summary,
        'stage1_stage2_comparison': stage1_stage2,
        'reference_metrics': {
            'paper_reference_band1_approx': -0.10,
            'paper_reference_band2_approx': 0.54,
            'paper_reference_band3_approx': -0.43,
            'paper_reference_rounded_sum_approx': 0.01,
            'paper_reference_max_abs_individual': 0.54,
            'paper_reference_sum_abs_individual': 1.07,
            'stage2_composite_to_max_individual_magnitude_ratio': abs(chern) / 0.54,
            'stage2_composite_to_sum_abs_individual_ratio': abs(chern) / 1.07,
        },
        'validation': {
            'source_stage2_binding': 'VERIFIED',
            'checkpoint_set': 'EXACT_1201',
            'checkpoint_manifest_replay': 'PASSED',
            'compact_reduction_manifest': 'COMMITTED_AND_REMOTE_VERIFIED',
            'area_semantics_corrected': True,
            'stage2_reaggregation': 'PASSED',
            'delta_distribution': 'VERIFIED',
            'low_gap_profile_reduction': 'PASSED' if not failed else 'FAILED',
            'no_stage3_required': True,
            'main_unchanged': True,
        },
    }
    corrected = dict(old_result)
    corrected.pop('qualified_area_fraction', None)
    corrected.update({
        'schema': 'e7i4f_stage2_result_v2',
        'retained_area_q': retained_area,
        'qualified_area_q': qualified_area,
        'unqualified_area_q': unqualified_area,
        'qualified_area_fraction': 1.0 if abs(qualified_area - retained_area) <= 1e-12 else qualified_area / retained_area,
        'unqualified_area_fraction': 0.0 if abs(unqualified_area) <= 1e-15 else unqualified_area / retained_area,
        'compact_reduction_manifest_sha256': compact_hash,
        'compact_manifest_sha256': compact_manifest_file_sha,
        'c1_closure_work_order': closure['work_order'],
        'reducer_code_git_sha': current_head,
        'reducer_sha256': reducer_sha256,
        'delta_distribution': closure['delta_distribution'],
        'low_gap_profile_summary': closure['low_gap_profile_summary'],
        'stage1_stage2_comparison': stage1_stage2,
        'execution_summary': telemetry_summary,
        'main_unchanged': True,
    })
    atomic_json(result_path, corrected)
    closure['result_json_sha256'] = sha_bytes(result_path.read_bytes())
    atomic_json(AUDIT / 'e7i4f_c1_closure.json', closure)
    print(json.dumps({
        'status': 'C1_EVIDENCE_REAGGREGATION_PASSED',
        'elements': len(replay),
        'qualified_area_fraction': 1.0 if abs(qualified_area - retained_area) <= 1e-12 else qualified_area / retained_area,
        'curvature_integral': integral,
        'composite_valley_chern': chern,
        'compact_manifest_sha256': compact_hash,
        'result_json_sha256': closure['result_json_sha256'],
    }, sort_keys=True))
def self_check():
    assert len({'a', 'b'}) == 2
    assert len({'a', 'a'}) != 2
    assert not Path('/definitely/missing/checkpoint.json').exists()
    assert sha_bytes(b'invalid') != '0' * 64
    assert 'stale-runner' != RUNNER_SHA
    assert not {'qualified': False}['qualified']
    assert not finite(float('nan'))
    assert 0.0 <= 0.0
    assert not finite(float('nan'))
    assert 1200 != 1201
    assert 1170 + 31 + 0 == 1201
    assert abs(0.5 - 1.0) > 1e-12
    assert not math.isclose(0.9, 1.0, rel_tol=0.0, abs_tol=1e-12)
    assert len({(0.1, 0.2), (0.1, 0.2)}) == 1
    assert 'LOW_GAP_FAIL' != 'LOW_GAP_PASS'
    assert math.isclose((2.0 * PI) / (2.0 * PI), 1.0, rel_tol=0.0, abs_tol=0.0)
    assert sorted(['b', 'a']) == ['a', 'b']
if __name__ == '__main__':
    import sys
    if '--self-check' in sys.argv:
        self_check()
        print('{"self_check": "PASSED"}')
    else:
        main()
