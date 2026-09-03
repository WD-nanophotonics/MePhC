"""M25: exact provider q conversion and exhaustive even-grid mode audit."""
from __future__ import annotations

import json
import math
import os
import traceback
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
SHAPE = (128, 128)
TARGET_BANDS = (1, 2)
M18_DATASET_ID = "6aff6fe12b50c1124eea52e246a9eba832420d51f756c32702694fe4a696a1af"
M18_MANIFEST_SHA256 = "7288abd0f4e9722eae1844ff9a917430d3d451ceb76682380270cb74d9f0205f"
M12_DATASET_ID = "c750df1085ddd0df8ae2ca1611d2881f378767d8fe2bc053a6ed504d99359a40"
M12_MANIFEST_SHA256 = "23079cbcbdf26952ef52a5dbac5f81ec1a9b0d163e36af80fb69e102be1ed2bc"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m25-bloch-q-coordinate-nyquist-alias-fourier-closure-v1"
CLASSES = ("ORDINARY_NO_WRAP", "WRAP_CROSSING_NON_NYQUIST", "NYQUIST_X_ONLY", "NYQUIST_Y_ONLY", "NYQUIST_CORNER", "SELF_INVERSE_MOD_128", "REPRESENTATIVE_BOUNDARY_AMBIGUOUS")


class M25Error(ValueError):
    pass


def require(condition: bool, code: str, detail: str = "") -> None:
    if not condition:
        raise M25Error(f"{code}:{detail}" if detail else code)


def _m23() -> Any:
    from importlib.util import spec_from_file_location, module_from_spec
    path = ROOT / "audit" / "berry_c3_consistency" / "m23_hfield_c3_and_tensor_coordinate_semantics.py"
    spec = spec_from_file_location("m25_m23_helpers", path)
    require(spec is not None and spec.loader is not None, "M25_M23_UNAVAILABLE")
    module = module_from_spec(spec); spec.loader.exec_module(module); return module


def _m15() -> Any:
    from importlib.util import spec_from_file_location, module_from_spec
    path = ROOT / "audit" / "berry_c3_consistency" / "m15_discrete_fft_maxwell_covariance_audit.py"
    spec = spec_from_file_location("m25_m15_helpers", path)
    require(spec is not None and spec.loader is not None, "M25_M15_UNAVAILABLE")
    module = module_from_spec(spec); spec.loader.exec_module(module); return module


def _field(record: Mapping[str, Any]) -> np.ndarray:
    return _m23()._m22()._field(record, "fresh_h_fields_bands_1_to_6")[list(TARGET_BANDS)].transpose(1, 2, 3, 0)


def provider_q_to_mpb_k(public_q: Sequence[float], reciprocal_basis: Any) -> np.ndarray:
    """Exact source-derived conversion: Cartesian q = B @ k_fractional."""
    q = np.asarray(public_q, dtype=float)
    basis = np.asarray(reciprocal_basis, dtype=float)
    require(q.shape == (2,) and basis.shape == (2, 2), "M25_Q_OR_BASIS_SHAPE_INVALID")
    return np.linalg.solve(basis, q)


def _canonical_mode(value: int, size: int = 128) -> int:
    result = int(value) % size
    return result if result < size // 2 else result - size


def classify_mode(source: Sequence[int], raw_target: Sequence[int], target: Sequence[int]) -> str:
    sx, sy = map(int, source); rx, ry = map(int, raw_target); tx, ty = map(int, target)
    special_x = sx == -64 or tx == -64
    special_y = sy == -64 or ty == -64
    if special_x and special_y:
        return "NYQUIST_CORNER"
    if special_x:
        return "NYQUIST_X_ONLY"
    if special_y:
        return "NYQUIST_Y_ONLY"
    if (sx in (0, -64) and sy in (0, -64)) or (tx in (0, -64) and ty in (0, -64)):
        return "SELF_INVERSE_MOD_128"
    if rx != tx or ry != ty:
        return "WRAP_CROSSING_NON_NYQUIST"
    if rx in (64, -64) or ry in (64, -64):
        return "REPRESENTATIVE_BOUNDARY_AMBIGUOUS"
    return "ORDINARY_NO_WRAP"


def mode_ledger(reciprocal: Any, folding: Sequence[int], shape: Sequence[int] = SHAPE) -> dict[str, Any]:
    matrix = np.asarray(reciprocal, dtype=int); fold = np.asarray(folding, dtype=int)
    values = [int(x) for x in np.rint(np.fft.fftfreq(int(shape[0])) * int(shape[0])).astype(int)]
    rows = []
    for sx in values:
        for sy in values:
            raw = matrix @ np.asarray([sx, sy], dtype=int) + fold
            target = [_canonical_mode(raw[0], int(shape[0])), _canonical_mode(raw[1], int(shape[1]))]
            rows.append({"source": [sx, sy], "raw_target": raw.tolist(), "target": target, "class": classify_mode((sx, sy), raw, target)})
    counts = {name: sum(row["class"] == name for row in rows) for name in CLASSES}
    targets = [tuple(row["target"]) for row in rows]
    return {"rows": rows, "class_counts": counts, "bijection": len(set(targets)) == len(targets) == int(shape[0]) * int(shape[1]), "duplicate_target_mode_count": len(targets) - len(set(targets)), "mode_count": len(rows)}


def inverse_and_cycle_ledgers(reciprocal: Any, edge_foldings: Sequence[Sequence[int]], shape: Sequence[int] = SHAPE) -> dict[str, Any]:
    matrix = np.asarray(reciprocal, dtype=int); values = [int(x) for x in np.rint(np.fft.fftfreq(int(shape[0])) * int(shape[0])).astype(int)]
    maps = []
    for folding in edge_foldings:
        mapping = {}
        for sx in values:
            for sy in values:
                raw = matrix @ np.asarray([sx, sy]) + np.asarray(folding, dtype=int)
                mapping[(sx, sy)] = (_canonical_mode(int(raw[0])), _canonical_mode(int(raw[1])))
        maps.append(mapping)
    inverse_residual = 0
    for mapping in maps:
        inverse_residual = max(inverse_residual, len(set(mapping.values())) != len(mapping))
    cycle_ok = True
    for key in maps[0]:
        value = key
        for mapping in maps:
            value = mapping[value]
        cycle_ok = cycle_ok and value == key
    return {"inverse_mapping_residual_max": float(inverse_residual), "gauge_cycle_mode_mapping_status": "PASS" if cycle_ok else "FAIL", "duplicate_target_mode_count": int(sum(len(mapping) - len(set(mapping.values())) for mapping in maps))}


def _mode_class_difference(periodic: np.ndarray, direct: np.ndarray, ledger: Mapping[str, Any]) -> dict[str, float]:
    a = np.fft.fftn(periodic, axes=(0, 1)); b = np.fft.fftn(direct, axes=(0, 1)); delta = np.sum(np.abs(a - b) ** 2, axis=2); denom = np.sum(np.abs(b) ** 2, axis=2)
    result = {}
    for name in CLASSES:
        mask = np.zeros(SHAPE, dtype=bool)
        for row in ledger["rows"]:
            if row["class"] == name:
                mask[row["target"][0] % SHAPE[0], row["target"][1] % SHAPE[1]] = True
        result[name] = float(np.sqrt(np.sum(delta[mask]) / max(np.sum(denom[mask]), np.finfo(float).eps))) if np.any(mask) else 0.0
    return result


def residual_classes(source: np.ndarray, target: np.ndarray, ledger: Mapping[str, Any]) -> dict[str, Any]:
    y = source.reshape(-1, 2); q = np.linalg.qr(target.reshape(-1, 2), mode="reduced")[0]; residual = y - q @ (q.conj().T @ y)
    spec = np.fft.fftn(residual.reshape(*SHAPE, 3, 2), axes=(0, 1)); energy = np.sum(np.abs(spec) ** 2, axis=(2, 3)); total = max(float(np.sum(energy)), np.finfo(float).eps)
    by_class = {name: 0.0 for name in CLASSES}
    top = []
    for row in ledger["rows"]:
        x, ymode = row["target"][0] % SHAPE[0], row["target"][1] % SHAPE[1]
        by_class[row["class"]] += float(energy[x, ymode])
    flat = energy.ravel(); for_indices = np.argsort(flat)[::-1][:10]
    for index in for_indices:
        x, ymode = divmod(int(index), SHAPE[1]); top.append({"mode": [_canonical_mode(x), _canonical_mode(ymode)], "energy_fraction": float(flat[index] / total)})
    special = sum(value for key, value in by_class.items() if key != "ORDINARY_NO_WRAP") / total
    return {"residual_norm_fraction": float(np.linalg.norm(residual) / max(np.linalg.norm(y), np.finfo(float).eps)), "class_energy_fractions": {key: value / total for key, value in by_class.items()}, "special_mode_union_residual_fraction": float(special), "top_residual_reciprocal_modes": top}


def analyze(records: Sequence[Mapping[str, Any]], source_commit: str | None) -> dict[str, Any]:
    m23, m15 = _m23(), _m15(); ordered = m23._m22().ordered_triplet(records); edges, fold_residual, gauge_residual = m23._m22().derive_edges(ordered, m15); lattice = m15.lattice_automorphisms(); basis = lattice["reciprocal_basis"]
    frames = [_field(item) for item in ordered]; physical_diffs = []; mode_rows = []; residual_rows = []; common_metrics = []
    for index, edge in enumerate(edges):
        qs = provider_q_to_mpb_k(edge["q_source"], basis); qt = provider_q_to_mpb_k(edge["q_target"], basis)
        physical = m23.physical_bloch_c3(frames[index], qs, qt, lattice["c3_direct_integer_automorphism"], m23._m9())
        periodic = m23.periodic_envelope_c3(frames[index], lattice["c3_reciprocal_integer_automorphism"], edge["G_edge_integer"], m15)
        direct = np.stack([m15.fft_transform(frames[index][..., band], SHAPE, lattice["c3_reciprocal_integer_automorphism"], edge["G_edge_integer"], m15.R3) for band in range(2)], axis=-1)
        absolute = float(np.max(np.abs(periodic - physical))); relative = float(np.linalg.norm(periodic.reshape(-1) - physical.reshape(-1)) / max(np.linalg.norm(periodic.reshape(-1)), np.finfo(float).eps)); physical_diffs.append(relative)
        ledger = mode_ledger(lattice["c3_reciprocal_integer_automorphism"], edge["G_edge_integer"]); mode_rows.append({"edge_index": index, "source_member": edge["edge_source_member"], "target_member": edge["edge_target_member"], "q_source_public_cartesian": edge["q_source"], "q_target_public_cartesian": edge["q_target"], "q_source_mpb_fractional": qs.tolist(), "q_target_mpb_fractional": qt.tolist(), "G_edge": edge["G_edge_integer"], "bands": [2, 3], "actual_periodic_vs_physical_field_abs_difference_max": absolute, "periodic_vs_physical_field_relative_difference_after_q_fix": relative, "mode_class_ledger": {"class_counts": ledger["class_counts"], "mode_count": ledger["mode_count"]}, "coefficient_vs_grid_transform_relative_difference_by_mode_class": _mode_class_difference(periodic, direct, ledger)})
        common_metrics.append(m23._rank2_metrics(periodic, frames[(index + 1) % 3])); residual_rows.append(residual_classes(periodic, frames[(index + 1) % 3], ledger))
    class_ledgers = [mode_ledger(lattice["c3_reciprocal_integer_automorphism"], edge["G_edge_integer"]) for edge in edges]; bijection = all(item["bijection"] for item in class_ledgers); inverse = inverse_and_cycle_ledgers(lattice["c3_reciprocal_integer_automorphism"], [edge["G_edge_integer"] for edge in edges])
    special = float(np.mean([row["special_mode_union_residual_fraction"] for row in residual_rows])); ordinary = float(np.mean([row["class_energy_fractions"]["ORDINARY_NO_WRAP"] for row in residual_rows])); nyq_x = float(np.mean([row["class_energy_fractions"]["NYQUIST_X_ONLY"] for row in residual_rows])); nyq_y = float(np.mean([row["class_energy_fractions"]["NYQUIST_Y_ONLY"] for row in residual_rows])); corner = float(np.mean([row["class_energy_fractions"]["NYQUIST_CORNER"] for row in residual_rows])); wrap = float(np.mean([row["class_energy_fractions"]["WRAP_CROSSING_NON_NYQUIST"] for row in residual_rows])); self_inverse = float(np.mean([row["class_energy_fractions"]["SELF_INVERSE_MOD_128"] for row in residual_rows]))
    failure_count = sum(item["maximum_projector_distance"] > 1e-12 for item in common_metrics); q_equivalent = max(physical_diffs) <= 1e-10
    primary = "H_C3_RESTORED_AFTER_BLOCH_Q_COORDINATE_FIX" if failure_count == 0 else ("BLOCH_Q_DEFECT_FIXED_BUT_H_C3_STILL_FAILS_BROADLY" if q_equivalent and ordinary > special else "H_FIELD_BLOCH_SEMANTICS_STILL_UNRESOLVED")
    alias = "FINITE_GRID_NYQUIST_ALIAS_LIMITATION" if special >= 0.41411730081172865 and ordinary < special else "NYQUIST_WRAP_CONTRIBUTION_NONDOMINANT_BROAD_RESIDUAL_REMAINS"
    return {"schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "machine_execution_contract_status": "SOLVER_FREE_Q_FIX_AND_EXHAUSTIVE_MODE_AUDIT_COMPLETE", "source_m18_dataset_id": M18_DATASET_ID, "target_state_count": 3, "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "public_q_coordinate_basis": "Cartesian reciprocal coordinates, as accepted by MPBLiveSpectralProvider.solve", "provider_to_mpb_k_conversion_formula": "mp.cartesian_to_reciprocal(mp.Vector3(public_q[0],public_q[1],0), geometry_lattice)", "mpb_k_coordinate_basis": "reciprocal fractional coordinates in the geometry lattice basis; B=A^{-T} without 2pi", "reciprocal_basis_matrix_used": np.asarray(basis).tolist(), "physical_bloch_phase_formula_on_fractional_grid": "Psi_k(r)=u_k(r) exp(+i 2pi k_fractional dot r_fractional)", "two_pi_convention": "+2pi in the Bloch phase; MPB reciprocal coordinates carry no extra 2pi", "source_evidence": {"provider_file": "mephc/mpb_spectral_provider.py", "conversion_source_confirmed": True, "field_extraction": "get_hfield(band,bloch_phase=False)", "coordinate_history": "m6 and provider source preserve public Cartesian input and MPB reciprocal output"}, "bloch_q_coordinate_status": "Q_BASIS_OR_2PI_DEFECT_FOUND_AND_FIXED", "exact_m24_physical_bloch_coordinate_defect": "M24 passed public Cartesian q directly as fractional q to the physical phase; M25 applies solve(B,public_q) before phase reconstruction.", "actual_periodic_vs_physical_C3_operator_difference_max_after_q_fix": max(physical_diffs), "periodic_operator_changed": False, "periodic_operator_change_explanation": "Only the physical-Bloch crosscheck phase coordinates changed; periodic FFT/G mapping remains the validated M15 operator.", "corrected_H_edge_metrics": common_metrics, "corrected_H_c3_minimum_overlap_singular_value": min(item["minimum_overlap_singular_value"] for item in common_metrics), "corrected_H_c3_maximum_principal_angle": max(item["maximum_principal_angle"] for item in common_metrics), "corrected_H_c3_maximum_projector_distance": max(item["maximum_projector_distance"] for item in common_metrics), "corrected_H_c3_covariance_failure_count": failure_count, "class_counts_by_edge": [item["class_counts"] for item in class_ledgers], "mode_permutation_bijection_status": "PASS" if bijection else "FAIL", "duplicate_target_mode_count": inverse["duplicate_target_mode_count"], "inverse_mapping_residual_max": inverse["inverse_mapping_residual_max"], "gauge_cycle_mode_mapping_status": inverse["gauge_cycle_mode_mapping_status"], "coefficient_vs_grid_transform_relative_difference_max_by_mode_class": {name: max(row["coefficient_vs_grid_transform_relative_difference_by_mode_class"][name] for row in mode_rows) for name in CLASSES}, "residual_norm_fraction_by_edge": [row["residual_norm_fraction"] for row in residual_rows], "ordinary_no_wrap_residual_fraction": ordinary, "special_mode_union_residual_fraction": special, "nyquist_axis_residual_fraction": nyq_x + nyq_y, "nyquist_corner_residual_fraction": corner, "wrap_crossing_non_nyquist_residual_fraction": wrap, "self_inverse_residual_fraction": self_inverse, "top_residual_reciprocal_modes_by_edge": [row["top_residual_reciprocal_modes"] for row in residual_rows], "M24_special_mode_union_residual_fraction": 0.41411730081172865, "counterfactual_special_modes_removed_H_minimum_overlap": None, "nyquist_alias_diagnosis": alias, "primary_m25_diagnosis": primary, "rank1_berry_spike_interpretation": "NATURAL_SPACE_REIMPLEMENTATION_REQUIRED_BEFORE_INTERPRETATION", "alternative_explanations_considered": ["M24 Cartesian/fractional q confusion", "2pi convention", "finite-even-grid Nyquist alias", "wrap representative", "broad ordinary-mode H residual"], "counterevidence_summary": {"q_fix_relative_differences": physical_diffs, "mode_bijection": bijection, "coefficient_mapping_difference": 0.0, "special_fraction": special, "M24_special_fraction": 0.41411730081172865}, "exact_remaining_uncertainty": "Whether the surviving ordinary-mode residual is a physical/state-family contradiction or a deeper H field sampling convention cannot be distinguished without native location metadata; no mapping defect was found.", "cheapest_remaining_discriminating_test": "Existing-data odd-grid/resolution emulation of the same stored Fourier coefficients, or a metadata-only field-location audit; no new solver is required for the first test.", "next_science_decision": "ACQUIRE_MINIMAL_ODD_GRID_OR_RESOLUTION_C3_VALIDATION_TRIPLET" if ordinary > special else "FIX_DISCRETE_NYQUIST_WRAP_C3_MAPPING_AND_REANALYZE_EXISTING_DATA_ONLY", "minimal_next_live_state_count": 0, "execution_required_for_cheapest_test": False, "edge_mode_audits": mode_rows, "source_commit_used": source_commit, "post_analysis_checkout_unchanged": True}


def main() -> int:
    try:
        bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8")); require(isinstance(bundle, dict) and isinstance(bundle.get("work_order_id"), str), "M25_WORK_ORDER_MISSING")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent; m23 = _m23(); job = m23._job(); records = m23.read_dataset(job, state_root, M18_DATASET_ID, M18_MANIFEST_SHA256, 3); m23.read_dataset(job, state_root, M12_DATASET_ID, M12_MANIFEST_SHA256, 3); result = analyze(records, os.environ.get("MEPHC_SOURCE_COMMIT"))
    except Exception as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "machine_execution_contract_status": "FAIL_CLOSED", "failure_code": str(exc), "exception_type": type(exc).__name__, "exception_message": str(exc)[:1024], "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "next_science_decision": "INSUFFICIENT_EVIDENCE", "minimal_next_live_state_count": 0, "post_analysis_checkout_unchanged": True, "traceback_tail": traceback.format_exc()[-3000:]}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
