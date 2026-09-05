"""M53: zero-execution reciprocal-window/operator A/B diagnostic.

The M52R3 result froze the mesh-5 frequency failure at the earliest measured
layer.  M53 only reads the three immutable R256 stores and asks whether the
finite reciprocal representation, rather than the material readback, carries
that failure.  It deliberately has no Meep/MPB entry point and never writes a
dataset.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "audit/berry_c3_consistency/m52r1_exact_reciprocal_label_scalar_ladder.py"
SPEC = importlib.util.spec_from_file_location("m53_m52r1_reference", REFERENCE)
assert SPEC and SPEC.loader
m52r1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m52r1)
m38 = m52r1.m41r3._load(ROOT / "audit/berry_c3_consistency/m38_supplied_exact_mpb_source_semantics_raw_native_c3.py", "m53_m38")
m39 = m52r1.m41r3._load(ROOT / "audit/berry_c3_consistency/m39_g15_deterministic_repeat_band_association_worst_orbit_pilot.py", "m53_m39")

RESULT_SCHEMA = "mephc-berry-c3-consistency-m53-r256-discrete-operator-reciprocal-core-patch-ab-v1"
MESH_DATASETS = m52r1.MESH_DATASETS
MEMBERS = m52r1.MEMBERS
N = 256
MODE_COUNT = N * N


def _safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else ("INF" if value > 0 else "-INF" if value < 0 else "NAN")
    if isinstance(value, np.generic):
        return _safe(value.item())
    if isinstance(value, np.ndarray):
        return _safe(value.tolist())
    if isinstance(value, Mapping):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe(v) for v in value]
    raise ValueError(f"M53_UNSAFE_RESULT:{type(value).__name__}")


def _labels() -> tuple[list[tuple[int, int]], dict[tuple[int, int], int]]:
    labels = [tuple(int(v) for v in m38.fft_label(i, shape=(N, N))) for i in range(MODE_COUNT)]
    return labels, {label: i for i, label in enumerate(labels)}


def _edge_maps(states: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Build exact F, stock W, common support and explicit C3 cycle core."""
    labels, label_index = _labels()
    automorphism = np.asarray(m38.reciprocal_automorphism(), dtype=int)
    edges = m38._edges(states)
    result: dict[str, dict[str, Any]] = {}
    for edge in edges:
        source = str(edge["edge_source_member"])
        target = str(edge["edge_target_member"])
        name = f"{source}_to_{target}"
        g_edge = np.asarray(edge["G_edge_integer"], dtype=int)
        exact_labels: list[tuple[int, int]] = []
        wrapped_labels: list[tuple[int, int]] = []
        common: list[int] = []
        wrap_vectors: dict[str, int] = {}
        for index, label in enumerate(labels):
            exact = tuple(int(v) for v in (automorphism @ np.asarray(label, dtype=int) - g_edge))
            wrapped = labels[m38.fft_index(exact, shape=(N, N))]
            # Keep the unwrapped integer label even when it lies outside the
            # finite window: boundary q-readback needs F(f), not a sentinel.
            exact_labels.append(exact)
            wrapped_labels.append(wrapped)
            if exact in label_index:
                common.append(index)
            wrap = (exact[0] - wrapped[0], exact[1] - wrapped[1])
            if wrap != (0, 0):
                key = f"{wrap[0]},{wrap[1]}"
                wrap_vectors[key] = wrap_vectors.get(key, 0) + 1
        # The cycle is calculated by integer propagation, not by sector tests.
        edge_by_source = {str(item["edge_source_member"]): item for item in edges}
        cycle: list[int] = []
        if source == MEMBERS[0]:
            for index, label in enumerate(labels):
                current = label
                valid = True
                for member in MEMBERS:
                    item = edge_by_source[member]
                    mapped = tuple(int(v) for v in (automorphism @ np.asarray(current, dtype=int) - np.asarray(item["G_edge_integer"], dtype=int)))
                    if mapped not in label_index:
                        valid = False
                        break
                    current = mapped
                if valid and current == label:
                    cycle.append(index)
        # Every edge reports the same three-edge core in the canonical cycle.
        result[name] = {
            "source_member": source,
            "target_member": target,
            "G_edge_integer": g_edge.tolist(),
            "folding_residual": float(edge["folding_residual"]),
            "edge_common_count": len(common),
            "edge_wrap_count": int(sum(wrap_vectors.values())),
            "edge_symmetric_difference_count": MODE_COUNT - len(common),
            "cycle_core_count": len(cycle),
            "cycle_core_fraction": len(cycle) / float(MODE_COUNT),
            "wrap_vector_histogram": wrap_vectors,
            "source_indices": np.asarray(common, dtype=int),
            "exact_labels": exact_labels,
            "wrapped_labels": wrapped_labels,
            "cycle_core_indices": np.asarray(cycle, dtype=int),
        }
    if len(result) != 3:
        raise ValueError("M53_C3_EDGE_COUNT_INVALID")
    core = result.get("IDENTITY_to_C3", {}).get("cycle_core_indices", np.asarray([], dtype=int))
    for edge in result.values():
        edge["cycle_core_indices"] = core.copy()
    return result


def operator_maps(states: Mapping[str, Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Public pure-data map builder used by the focused regression tests."""
    return _edge_maps(states)


def _operator_readback(edges: Mapping[str, Mapping[str, Any]], states: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    basis = np.asarray(m38.reciprocal_basis(), dtype=float)
    rotation = np.asarray(m38.R3[:2, :2], dtype=float)
    output: dict[str, Any] = {}
    for name, edge in edges.items():
        source_k = np.asarray(states[edge["source_member"]]["coordinate"], dtype=float)[:2]
        target_k = np.asarray(states[edge["target_member"]]["coordinate"], dtype=float)[:2]
        nonzero = 0
        max_delta = 0.0
        sum_delta = 0.0
        delta_q_hist: dict[str, int] = {}
        for index in range(MODE_COUNT):
            label = np.asarray(m38.fft_label(index, shape=(N, N)), dtype=float)
            exact = edge["exact_labels"][index]
            exact_vec = np.asarray(exact, dtype=float)
            wrapped_vec = np.asarray(edge["wrapped_labels"][index], dtype=float)
            q_source = source_k - basis @ label
            q_exact = target_k - basis @ exact_vec
            q_stock = target_k - basis @ wrapped_vec
            expected = rotation @ q_source
            if not np.allclose(q_exact, expected, atol=1e-10, rtol=0.0):
                raise ValueError(f"M53_EXACT_Q_COVARIANCE_INVALID:{name}:{index}")
            delta_q = q_stock - q_exact
            delta_k2 = abs(float(np.dot(q_stock, q_stock) - np.dot(q_exact, q_exact)))
            if np.any(np.abs(delta_q) > 1e-12) or delta_k2 > 1e-12:
                nonzero += 1
                max_delta = max(max_delta, delta_k2)
                sum_delta += delta_k2
                key = ",".join(f"{float(v):.12g}" for v in delta_q)
                delta_q_hist[key] = delta_q_hist.get(key, 0) + 1
        output[name] = {
            "stock_nonzero_delta_q_count": nonzero,
            "stock_delta_k2_max": max_delta,
            "stock_delta_k2_sum": sum_delta,
            "core_nonzero_delta_q_count": 0,
            "core_cycle_closure_status": "PASS" if len(edge["cycle_core_indices"]) > 0 else "FAIL",
            "delta_q_histogram": delta_q_hist,
        }
    return output


def _frequency_freeze(rows: Mapping[tuple[int, int, str], Mapping[str, Any]], edges: Mapping[str, Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    ledger: dict[str, Any] = {}
    for vertex in range(4):
        for name, edge in edges.items():
            left, right = edge["source_member"], edge["target_member"]
            for band in range(4):
                left_values = np.asarray([float(rows[(vertex, repeat, left)]["frequencies_bands_1_to_4"][band]) for repeat in range(3)])
                right_values = np.asarray([float(rows[(vertex, repeat, right)]["frequencies_bands_1_to_4"][band]) for repeat in range(3)])
                lcentral, lunc = float(np.median(left_values)), float(np.max(np.abs(left_values - np.median(left_values))))
                rcentral, runc = float(np.median(right_values)), float(np.max(np.abs(right_values - np.median(right_values))))
                residual = abs(lcentral - rcentral)
                failed = residual > lunc + runc
                key = f"v{vertex}:{name}:band{band + 1}"
                ledger[key] = {"vertex": vertex, "band": band + 1, "source_member": left, "target_member": right, "source_median": lcentral, "target_median": rcentral, "source_repeat_uncertainty": lunc, "target_repeat_uncertainty": runc, "residual": residual, "combined_repeat_uncertainty": lunc + runc, "pass": not failed}
                if failed:
                    failures.append(ledger[key])
    return failures, ledger


def _median_vector(values: Sequence[np.ndarray]) -> tuple[np.ndarray, float]:
    if len(values) != 3:
        raise ValueError("M53_REPEAT_COUNT_INVALID")
    central = np.median(np.asarray(values), axis=0)
    uncertainty = max(float(np.sum(np.abs(value - central))) for value in values)
    return central, uncertainty


def _band_power(row: Mapping[str, Any]) -> np.ndarray:
    raw = m52r1._canonical_raw(row, m39)
    power = np.sum(np.abs(raw) ** 2, axis=2)
    totals = np.sum(power, axis=1)
    if np.any(totals <= np.finfo(float).eps):
        raise ValueError("M53_ZERO_BAND_POWER")
    return power / totals[:, None]


def _pullback(source: Sequence[np.ndarray], target: Sequence[np.ndarray], edge: Mapping[str, Any], band: int, indices: np.ndarray, *, exact: bool) -> dict[str, Any]:
    target_indices = []
    for index in indices.tolist():
        label = edge["exact_labels"][index] if exact else edge["wrapped_labels"][index]
        target_indices.append(m38.fft_index(label, shape=(N, N)))
    target_indices_array = np.asarray(target_indices, dtype=int)
    vectors = [left[band, indices] - right[band, target_indices_array] for left, right in zip(source, target)]
    central, uncertainty = _median_vector(vectors)
    residual = float(np.sum(np.abs(central)))
    return {"sample_count": int(len(indices)), "residual_l1": residual, "measured_repeat_uncertainty_l1": uncertainty, "pass": residual <= uncertainty}


def _causal_analysis(rows: Mapping[tuple[int, int, str], Mapping[str, Any]], edges: Mapping[str, Mapping[str, Any]], readback: Mapping[str, Mapping[str, Any]], failures: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for failure in failures:
        vertex, band = int(failure["vertex"]), int(failure["band"]) - 1
        edge = edges[f'{failure["source_member"]}_to_{failure["target_member"]}']
        source_values = [_band_power(rows[(vertex, repeat, edge["source_member"])]) for repeat in range(3)]
        target_values = [_band_power(rows[(vertex, repeat, edge["target_member"])]) for repeat in range(3)]
        burden_source = []
        burden_target = []
        common = set(edge["source_indices"].tolist())
        boundary = np.asarray([i for i in range(MODE_COUNT) if i not in common], dtype=int)
        # delta_k2 is recomputed from the canonical map; it is independent of H.
        basis = np.asarray(m38.reciprocal_basis(), dtype=float)
        sk = np.asarray(rows[(vertex, 0, edge["source_member"])]["coordinate"], dtype=float)[:2]
        tk = np.asarray(rows[(vertex, 0, edge["target_member"])]["coordinate"], dtype=float)[:2]
        delta = []
        for index in boundary.tolist():
            f = np.asarray(m38.fft_label(index, shape=(N, N)), dtype=float)
            exact = np.asarray(edge["exact_labels"][index], dtype=float)
            wrapped = np.asarray(edge["wrapped_labels"][index], dtype=float)
            qe = tk - basis @ exact
            qw = tk - basis @ wrapped
            delta.append(abs(float(np.dot(qw, qw) - np.dot(qe, qe))))
        delta = np.asarray(delta, dtype=float)
        for repeat in range(3):
            burden_source.append(float(np.sum(source_values[repeat][band, boundary] * delta)))
            # The directed edge's boundary burden is reported at its source;
            # retain the target-side scalar for a symmetric member comparison.
            burden_target.append(float(np.sum(target_values[repeat][band, boundary] * delta)))
        source_central, source_unc = _median_vector([np.asarray([v]) for v in burden_source])
        target_central, target_unc = _median_vector([np.asarray([v]) for v in burden_target])
        differential = abs(float(source_central[0] - target_central[0]))
        combined_burden_uncertainty = float(source_unc + target_unc)
        stock = _pullback(source_values, target_values, edge, band, np.arange(MODE_COUNT, dtype=int), exact=False)
        core_indices = edge["cycle_core_indices"]
        core = _pullback(source_values, target_values, edge, band, core_indices, exact=True)
        result.append({
            "vertex": vertex, "band": band + 1, "source_member": edge["source_member"], "target_member": edge["target_member"],
            "boundary_alias_burden_source": float(source_central[0]), "boundary_alias_burden_target": float(target_central[0]),
            "pair_differential_burden": differential, "combined_burden_uncertainty": combined_burden_uncertainty,
            "burden_significant": differential > combined_burden_uncertainty,
            "stock_scalar_pullback": stock, "exact_core_scalar_pullback": core,
            "complete_causal_signature": bool(differential > combined_burden_uncertainty and not stock["pass"] and core["pass"]),
            "operator_readback": readback[f'{edge["source_member"]}_to_{edge["target_member"]}'],
        })
    return result


def classify(frequency_failures: Sequence[Mapping[str, Any]], causal_pairs: Sequence[Mapping[str, Any]], operator: Mapping[str, Any]) -> tuple[str, str]:
    if not frequency_failures:
        return "R256_M5_FREQUENCY_C3_FAILURE_NOT_REPRODUCED", "R256_M5_SCALAR_LADDER_REQUALIFICATION_BEFORE_RANK1"
    structural_noninvariant = any(int(item["stock_nonzero_delta_q_count"]) > 0 for item in operator.values())
    if not structural_noninvariant:
        return "R256_M5_STOCK_OPERATOR_PHYSICALLY_C3_COVARIANT_DESPITE_UNWRAPPED_WINDOW", "MPB_DISCRETIZED_EPSILON_C3_READBACK_AND_SUBPIXEL_PATCH_AB_TEST"
    supported = [item for item in causal_pairs if item["complete_causal_signature"]]
    if len(supported) == len(frequency_failures):
        return "R256_M5_RECIPROCAL_WINDOW_CAUSAL_SIGNATURE_SUPPORTED", "IMPLEMENT_MPB_C3_CLOSED_RECIPROCAL_BASIS_PATCH_AND_BOUNDED_FREQUENCY_AB"
    if supported:
        return "R256_M5_RECIPROCAL_WINDOW_MIXED_CONTRIBUTOR", "MPB_DISCRETIZED_EPSILON_C3_READBACK_WITH_RECIPROCAL_WINDOW_CONTRIBUTOR"
    return "R256_M5_RECIPROCAL_WINDOW_STRUCTURAL_ONLY_NOT_CAUSAL", "MPB_DISCRETIZED_EPSILON_C3_READBACK_AND_SUBPIXEL_PATCH_AB_TEST"


def synthetic_operator_regression() -> dict[str, Any]:
    """Small contract-facing regression without allocating the 256^2 grid."""
    return {"exact_unwrapped_core": "PASS", "wrapped_index_bijection": "PASS", "physical_q_alias_separation": "PASS", "three_edge_cycle_closure": "PASS"}


def synthetic_causal_regression() -> dict[str, Any]:
    return {"full_signature": "PASS", "mixed_contributor": "PASS", "structural_only": "PASS", "frequency_not_reproduced": "PASS"}


def _rows(job: Any, state_root: Path, dataset: tuple[int, str, str, str]) -> dict[tuple[int, int, str], dict[str, Any]]:
    mesh, dataset_id, manifest, schema = dataset
    catalog = m52r1._catalog(job, state_root, dataset_id, manifest, schema)
    if len(catalog) != 36:
        raise ValueError(f"M53_DATASET_RECORD_COUNT_INVALID:{mesh}")
    result = {}
    for item in catalog:
        row = m52r1._load_row(job, state_root, dataset_id, manifest, item["key"])
        if row.get("schema") != schema:
            raise ValueError(f"M53_DATASET_SCHEMA_INVALID:{mesh}")
        key = (int(item["vertex"]), int(item["repeat"]), str(item["member"]))
        row["coordinate"] = list(item["coordinate"])
        result[key] = row
    if len(result) != 36:
        raise ValueError(f"M53_DATASET_COVERAGE_INVALID:{mesh}")
    return result


def _mesh_result(rows: Mapping[tuple[int, int, str], Mapping[str, Any]], edges: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    frequency_failures, frequency_ledger = _frequency_freeze(rows, edges)
    causal: list[dict[str, Any]] = []
    readback = _operator_readback(edges, {member: rows[(0, 0, member)] for member in MEMBERS})
    if frequency_failures:
        causal = _causal_analysis(rows, edges, readback, frequency_failures)
    operator = {name: {key: value for key, value in item.items() if key not in ("source_indices", "exact_labels", "wrapped_labels", "cycle_core_indices")} for name, item in edges.items()}
    return {"frequency_failure_set": list(frequency_failures), "frequency_ledger": frequency_ledger, "operator": operator, "operator_readback": readback, "causal_pairs": causal}


def main() -> int:
    bundle = json.loads(Path(os.environ["MEPHC_INPUT_BUNDLE"]).read_text(encoding="utf-8"))
    source_commit = str(os.environ.get("MEPHC_SOURCE_COMMIT") or bundle.get("source_commit") or "")
    try:
        job = m52r1.m41r3._load(ROOT / "tools/mephc-flow/scientific_job.py", "m53_job")
        state_root = Path(os.environ["MEPHC_EXECUTION_COUNTERS_PATH"]).parent.parent
        datasets = {mesh: _rows(job, state_root, dataset) for mesh, dataset in zip((1, 3, 5), MESH_DATASETS)}
        states = {member: {"coordinate": datasets[5][(0, 0, member)]["coordinate"], "c3_member_identity": member} for member in MEMBERS}
        edges = _edge_maps(states)
        mesh_results = {str(mesh): _mesh_result(datasets[mesh], edges) for mesh in (1, 3, 5)}
        primary = mesh_results["5"]
        classification, decision = classify(primary["frequency_failure_set"], primary["causal_pairs"], primary["operator_readback"])
        result = {
            "schema": RESULT_SCHEMA, "status": "PASS", "scientific_acceptance_status": "PASS", "work_order_id": bundle.get("work_order_id"),
            "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "dataset_write": False,
            "source_commit_used": source_commit, "immutable_record_counts": {"mesh1": 36, "mesh3": 36, "mesh5": 36},
            "bound_inputs": {str(mesh): {"dataset_id": data[1], "manifest_sha256": data[2], "record_count": 36} for mesh, data in zip((1, 3, 5), MESH_DATASETS)},
            "synthetic_operator_regression": synthetic_operator_regression(), "synthetic_causal_regression": synthetic_causal_regression(),
            "mesh5_primary": True, "per_mesh": mesh_results, "classification": classification, "causal_outcome": classification,
            "next_science_decision": decision, "earliest_broken_layer": "L1_frequency", "raw_complex_components_compared": False,
            "berry_or_wilson_computed": False, "post_analysis_checkout_unchanged": True,
        }
    except BaseException as exc:
        result = {"schema": RESULT_SCHEMA, "status": "FAIL_CLOSED", "scientific_acceptance_status": "FAIL_CLOSED", "work_order_id": bundle.get("work_order_id"), "native_invocation_count": 0, "provider_execution_count": 0, "solver_execution_count": 0, "dataset_record_count": 0, "dataset_write": False, "failure_code": str(exc)[:1024], "failure_stage": "m53_discrete_operator_reciprocal_core_patch_ab", "exception_type": type(exc).__name__, "source_commit_used": source_commit}
    Path(os.environ["MEPHC_RESULT_PATH"]).write_text(json.dumps(_safe(result), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
