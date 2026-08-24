"""E9F.C1.RP2 bounded six-point diagnostic.

The parent side is deliberately standard-library-only.  Native MPB imports
are confined to the ``--worker`` child, whose result is accepted only after
the complete sample/resolution/stencil identity and diagnostic schema have
been checked.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence

from audit.infrastructure.campaign_runtime import (
    CampaignIdentity,
    CampaignRuntime,
    CampaignRuntimeError,
    current_rss_kib,
    semantic_plan_fingerprint,
    sha256_file,
)

WORK_ORDER = "TRILATT-E9F-C1-RP2-C1-20260824-231"
PHASE = "E9F.C1.RP2.C1"
STOP_AFTER = "E9F_C1_RP2_C1_REPORT"
CONTRACT_REL = Path("audit/e9f/rp2_c1_execution_contract.json")
POLICY_REL = Path("audit/e9f/rp1_recovery_policy_contract.json")
RUNNER_MARKER = "run_e9f_c1_rp2_c1.py"
RESOLUTIONS = (64, 96)
STENCILS = ("1/72", "1/144")
ZERO_BANDS = (2, 3)
RANK2 = (2, 3)
ASSOCIATION_WINDOW = (2, 3)
L0_WINDOW = (1, 2, 3, 4)
WORKER_SCHEMA = "trilatt_e9f_c1_rp2_c1_worker_v1"
RESULT_SCHEMA = "trilatt_e9f_c1_rp2_c1_result_v1"
ORIGINAL_RP2_EXECUTION_SHA = "8121dbfba352b1a77551213771694d25c1bf3f01"
NUM_BANDS = 6
SOLVER_TOLERANCE = 1e-7
MESH_SIZE = 3
REPRESENTATION = "mpb_live_energy_eh_v1"
POLARIZATION = "TE"
EIGEN_TOLERANCE = 1e-10


def _sha_json(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _json_value(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return _json_value(value.tolist())
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite value cannot enter RP2 evidence")
        return value
    raise TypeError(f"unsupported JSON value: {type(value).__name__}")


def load_execution_contract(root: Path) -> dict[str, Any]:
    value = json.loads((root / CONTRACT_REL).read_text(encoding="utf-8"))
    if value.get("schema") != "trilatt_e9f_c1_rp2_c1_execution_contract_v1":
        raise CampaignRuntimeError("RP2_EXECUTION_CONTRACT_SCHEMA_MISMATCH")
    if value.get("work_order_id") != WORK_ORDER or value.get("phase") != PHASE:
        raise CampaignRuntimeError("RP2_EXECUTION_CONTRACT_WORK_ORDER_MISMATCH")
    if value.get("matrix", {}).get("resolutions") != list(RESOLUTIONS):
        raise CampaignRuntimeError("RP2_EXECUTION_RESOLUTION_MATRIX_MISMATCH")
    if value.get("matrix", {}).get("stencils") != list(STENCILS):
        raise CampaignRuntimeError("RP2_EXECUTION_STENCIL_MATRIX_MISMATCH")
    if value.get("matrix", {}).get("optional_escalation") is not False:
        raise CampaignRuntimeError("RP2_OPTIONAL_ESCALATION_MUST_BE_FALSE")
    if value.get("scientific_firewall", {}).get("diagnostic_only", True) is False:
        raise CampaignRuntimeError("RP2_DIAGNOSTIC_FIREWALL_MUTATED")
    if value.get("l0", {}).get("zero_based_window") != list(L0_WINDOW):
        raise CampaignRuntimeError("RP2_L0_ZERO_BASED_WINDOW_MISMATCH")
    if value.get("raw_association", {}).get("candidate_window_zero_based") != list(ASSOCIATION_WINDOW):
        raise CampaignRuntimeError("RP2_ASSOCIATION_WINDOW_MISMATCH")
    if value.get("matrix", {}).get("matrix_entry_count") != 24 or value.get("matrix", {}).get("logical_worker_count") != 12:
        raise CampaignRuntimeError("RP2_FIXED_MATRIX_SIZE_MISMATCH")
    return value


def load_policy(root: Path) -> dict[str, Any]:
    contract = json.loads((root / POLICY_REL).read_text(encoding="utf-8"))
    from audit.e9f.rp1_policy import validate_policy_contract

    validate_policy_contract(contract, root)
    return contract


def _sample_records(policy: Mapping[str, Any]) -> list[dict[str, Any]]:
    matrix = policy["rp2_diagnostic_matrix"]
    requested = matrix["fixed_sample_ids"]
    records = policy["immutable_inputs"]["failed_sample_records"]
    by_id = {row["sample_id"]: row for row in records}
    if len(requested) != 6 or len(set(requested)) != 6 or set(requested) - set(by_id):
        raise CampaignRuntimeError("RP2_POLICY_SAMPLE_SET_INVALID")
    selected = [dict(by_id[sample_id]) for sample_id in requested]
    selected.sort(key=lambda row: int(row["sample_index"]))
    if [row["sample_index"] for row in selected] != sorted(row["sample_index"] for row in selected):
        raise CampaignRuntimeError("RP2_POLICY_SAMPLE_INDEX_INVALID")
    return selected


def build_plan(root: Path) -> list[dict[str, Any]]:
    """Derive exactly twelve logical workers from the immutable policy."""
    execution = load_execution_contract(root)
    policy = load_policy(root)
    rows: list[dict[str, Any]] = []
    for sample in _sample_records(policy):
        for resolution in execution["matrix"]["resolutions"]:
            source_id = str(sample["sample_id"])
            worker_id = f"{source_id}::resolution={int(resolution)}"
            rows.append({
                "sample_id": worker_id,
                "source_sample_id": source_id,
                "source_sample_index": int(sample["sample_index"]),
                "sample_index": len(rows),
                "grid_index": [
                    int(source_id.split("grid_i=")[1].split(";")[0]),
                    int(source_id.split("grid_j=")[1].split(";")[0]),
                ],
                "resolution": int(resolution),
                "authoritative_coordinate": [float(x) for x in sample["center"]],
                "public_q": [float(x) for x in sample["center"]],
                "topology_id": "E9F_C1_RP2_LOW_GAP_POINTWISE_DIAGNOSTIC",
            })
    if len(rows) != 12 or len({row["sample_id"] for row in rows}) != 12:
        raise CampaignRuntimeError("RP2_LOGICAL_WORKER_MATRIX_INVALID")
    return rows


def matrix_entry_keys() -> set[tuple[str, str]]:
    return {(row["sample_id"], stencil) for row in build_plan(Path(__file__).resolve().parents[2]) for stencil in STENCILS}


def _row_by_worker_id(root: Path, worker_id: str) -> dict[str, Any]:
    rows = {row["sample_id"]: row for row in build_plan(root)}
    try:
        return rows[worker_id]
    except KeyError as exc:
        raise CampaignRuntimeError("RP2_UNKNOWN_WORKER_ID") from exc


def validate_worker_identity(row: Mapping[str, Any], *, worker_id: str, resolution: int, coordinate: Sequence[float]) -> None:
    if worker_id != row["sample_id"] or int(resolution) != int(row["resolution"]):
        raise CampaignRuntimeError("RP2_WORKER_ID_OR_RESOLUTION_MISMATCH")
    if len(coordinate) != 2 or any(float(a) != float(b) for a, b in zip(coordinate, row["authoritative_coordinate"])):
        raise CampaignRuntimeError("RP2_WORKER_COORDINATE_MISMATCH")


def assert_parent_solver_free() -> None:
    loaded = sorted(
        name for name in sys.modules
        if name == "meep" or name.startswith("meep.") or name == "mpb" or name.startswith("mpb.")
    )
    if loaded:
        raise CampaignRuntimeError(f"RP2_PARENT_NATIVE_IMPORT_DETECTED:{loaded}")


def _proc_cmdline(pid: int) -> str:
    try:
        return (Path("/proc") / str(pid) / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="replace")
    except (OSError, UnicodeError):
        return ""


def scan_worker_processes(worker_id: str | None = None) -> list[int]:
    if not Path("/proc").is_dir():
        raise CampaignRuntimeError("RP2_ORPHAN_INSPECTION_UNAVAILABLE")
    found = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        command = _proc_cmdline(int(entry.name))
        if RUNNER_MARKER not in command or "--worker" not in command:
            continue
        if worker_id is not None and worker_id not in command:
            continue
        found.append(int(entry.name))
    return sorted(found)


def run_reaped_child(command: Sequence[str], worker_id: str, *, timeout_seconds: float = 720.0) -> tuple[dict[str, Any], dict[str, Any]]:
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise CampaignRuntimeError(f"RP2_NATIVE_CHILD_TIMEOUT:{worker_id}") from exc
    direct_pid_gone = not (Path("/proc") / str(process.pid)).exists()
    orphan_pids = [pid for pid in scan_worker_processes(worker_id) if pid != process.pid]
    measurement = {
        "worker_id": worker_id,
        "launched_pid": int(process.pid),
        "returncode": int(process.returncode),
        "direct_pid_gone": bool(direct_pid_gone),
        "orphan_pids": orphan_pids,
        "orphan_count": len(orphan_pids),
    }
    if not direct_pid_gone or orphan_pids:
        raise CampaignRuntimeError(f"RP2_NATIVE_ORPHAN_DETECTED:{measurement}")
    if process.returncode != 0:
        raise CampaignRuntimeError(f"RP2_NATIVE_CHILD_FAILED:{worker_id}:{process.returncode}:{stderr[-600:]}")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise CampaignRuntimeError(f"RP2_NATIVE_CHILD_JSON_INVALID:{worker_id}:{stderr[-600:]}") from exc
    if not isinstance(payload, dict):
        raise CampaignRuntimeError("RP2_NATIVE_CHILD_RESULT_NOT_OBJECT")
    return payload, measurement


def worker_command(root: Path, row: Mapping[str, Any]) -> list[str]:
    return [
        sys.executable, str(root / "audit/e9f/run_e9f_c1_rp2_c1.py"), "--worker",
        "--root", str(root), "--worker-id", str(row["sample_id"]),
        "--resolution", str(row["resolution"]),
        "--coordinate-json", json.dumps(row["authoritative_coordinate"], separators=(",", ":")),
    ]


def _unavailable(reason: str, *, category: str = "PHYSICAL_OR_NUMERICAL_DIAGNOSTIC") -> dict[str, Any]:
    return {"status": "NOT_AVAILABLE_WITH_REASON", "reason": str(reason), "unavailability_class": category}


def _reported(value: Mapping[str, Any]) -> dict[str, Any]:
    return {"status": "DIAGNOSTIC_REPORTED", **dict(value)}


def _snapshot_record(raw: Any, *, nominal_q: Sequence[float], manifest_q: Sequence[float], identity_key: str) -> dict[str, Any]:
    evaluated = [float(x) for x in raw.k_point]
    return {
        "NOMINAL_Q": [float(x) for x in nominal_q],
        "MANIFEST_Q": [float(x) for x in manifest_q],
        "EVALUATED_Q": evaluated,
        "frequencies": [float(x) for x in raw.frequencies],
        "physical_cache_identity": identity_key,
        "provider_representation": raw.provenance.get("representation"),
    }


def _solve_point(provider: Any, preflight: Any, geometry: Mapping[str, Any], background: Any, *, nominal_q: Sequence[float], manifest_q: Sequence[float], resolution: int, cache: dict[str, tuple[Any, dict[str, Any]]], identities: Any, counters: dict[str, int]) -> tuple[Any, dict[str, Any]]:
    geometry_digest = _sha_json(_json_value(geometry))
    material_digest = _sha_json({"default_material_epsilon": 7.0225, "geometry_digest": geometry_digest})
    provenance = {
        "geometry_digest": geometry_digest,
        "material_reference_digest": material_digest,
        "coordinate_mapping_digest": preflight.mapping_digest,
        "resolution": int(resolution),
        "num_bands": NUM_BANDS,
        "polarization": POLARIZATION,
        "provider_representation": REPRESENTATION,
        "eigensolver_tolerance": SOLVER_TOLERANCE,
        "deterministic": True,
        "mesh_size": MESH_SIZE,
    }
    request_key = _sha_json({"schema": "rp2_observed_request_binding_v1", "NOMINAL_Q": list(nominal_q), "MANIFEST_Q": list(manifest_q), **provenance})
    if request_key in cache:
        counters["cache_hits"] += 1
        raw, record = cache[request_key]
        return raw, record
    counters["solver_requests"] += 1
    raw = provider.solve(tuple(float(x) for x in manifest_q))
    evaluated_q = tuple(float(x) for x in raw.k_point)
    from mephc.valley_benchmark import PhysicalSolveIdentity

    identity = PhysicalSolveIdentity(
        geometry_digest=geometry_digest,
        material_reference_digest=material_digest,
        coordinate_mapping_digest=preflight.mapping_digest,
        evaluated_q=evaluated_q,
        resolution=int(resolution),
        num_bands=NUM_BANDS,
        polarization=POLARIZATION,
        provider_representation=REPRESENTATION,
        eigensolver_tolerance=SOLVER_TOLERANCE,
        deterministic=True,
        mesh_size=MESH_SIZE,
    )
    identity_key = identities.register(identity)
    record = _snapshot_record(raw, nominal_q=nominal_q, manifest_q=manifest_q, identity_key=identity_key)
    cache[request_key] = (raw, record)
    return raw, record


class DiagnosticAdapterPreconditionError(ValueError):
    """An adapter/API precondition failure that must stop a campaign."""


def _gram_diagnostics(raw: Any, selected: Sequence[int] = ASSOCIATION_WINDOW) -> dict[str, Any]:
    import numpy as np
    gram=np.asarray(raw.gram_matrix,dtype=np.complex128)
    full_offdiag=max((float(abs(gram[i,j])) for i in range(gram.shape[0]) for j in range(gram.shape[1]) if i!=j),default=0.0)
    pair=np.asarray(gram[np.ix_(list(selected),list(selected))],dtype=np.complex128)
    pair_offdiag=max((float(abs(pair[i,j])) for i in range(pair.shape[0]) for j in range(pair.shape[1]) if i!=j),default=0.0)
    pair_norm=max((float(abs(pair[i,i]-1.0)) for i in range(pair.shape[0])),default=0.0)
    return {"full_six_state_orthogonality_status":str(raw.orthogonality_status),"full_six_state_max_off_diagonal_gram":full_offdiag,"full_six_state_max_normalization_error":float(raw.max_normalization_error),"full_six_state_orthogonality_tolerance":float(raw.orthogonality_tolerance),"selected_pair_zero_based":list(selected),"selected_pair_max_off_diagonal_gram":pair_offdiag,"selected_pair_max_normalization_error":pair_norm,"selected_pair_validation_tolerance":1e-10,"selected_pair_representation_qualified":bool(pair_offdiag<=1e-10 and pair_norm<=1e-10)}


def _associate_vertices(values: Sequence[Mapping[str, Any]], raw_thresholds: Any) -> tuple[list[dict[int, int]], list[dict[str, Any]]]:
    from mephc.spectral_association import associate_raw_states
    maps=[{branch:branch for branch in ASSOCIATION_WINDOW}]; evidence=[]
    for index,value in enumerate(values):
        if not value["gram_diagnostics"]["selected_pair_representation_qualified"]:
            raise DiagnosticAdapterPreconditionError("E9F_C1_RP2_C1_SELECTED_PAIR_REPRESENTATION_UNQUALIFIED_FAIL_CLOSED")
        right=(index+1)%len(values)
        left_states=[value["raw"].raw_eigenstates[maps[index][branch]] for branch in ASSOCIATION_WINDOW]
        right_states=[values[right]["raw"].raw_eigenstates[branch] for branch in ASSOCIATION_WINDOW]
        try:
            association=associate_raw_states(left_states,right_states,thresholds=raw_thresholds)
        except (TypeError,ValueError,RuntimeError) as exc:
            raise DiagnosticAdapterPreconditionError(f"RAW_ASSOCIATION_API_PRECONDITION_FAILURE:{exc}") from exc
        evidence.append({"edge":[index,right],"candidate_window_zero_based":list(ASSOCIATION_WINDOW),"physical_labels_initial_to_solver_slot":{"2":2,"3":3} if index==0 else None,"status":association.status,"matched_by_solver_index":[list(pair) for pair in association.matched_by_solver_index],"matched_probabilities":list(association.matched_probabilities),"row_margins":list(association.row_margins),"column_margins":list(association.column_margins),"global_assignment_margin":association.global_assignment_margin,"evidence":list(association.evidence),"left_pair_gram":value["gram_diagnostics"],"right_pair_gram":values[right]["gram_diagnostics"]})
        if association.status!="CLEAR": raise ValueError(f"RAW_ASSOCIATION_{association.status}:{index}")
        mapping=dict(association.matched_by_solver_index)
        next_map={branch:mapping[maps[index][branch]] for branch in ASSOCIATION_WINDOW}
        if right==0:
            if any(next_map[branch]!=maps[0][branch] for branch in ASSOCIATION_WINDOW): raise ValueError("RAW_ASSOCIATION_CLOSED_LOOP_MISMATCH")
        else: maps.append(next_map)
    return maps,evidence

def _frame(raw: Any, index: int, q: Sequence[float], rank: int) -> Any:
    import numpy as np
    from mephc.eigenspace import EigenSubspace

    indices = [index] if rank == 1 else list(RANK2)
    vectors = [np.asarray(raw.normalized_vectors[item], dtype=np.complex128) for item in indices] if rank == 2 else [np.asarray(raw.normalized_vectors[index], dtype=np.complex128)]
    return EigenSubspace(
        k_point=tuple(float(x) for x in q),
        frame=np.column_stack(vectors),
        eigenvalues=tuple(float(raw.frequencies[item]) for item in indices),
        solver_indices=tuple(indices),
        metadata={"source": "RP2 associated raw MPB E+H state", "rank": rank, "solver_slot_is_not_physical_identity": True},
    )


def _excluded(frequencies: Sequence[float], selected: Sequence[int]) -> tuple[float, ...]:
    return tuple(float(value) for index, value in enumerate(frequencies) if index not in set(selected))


def _contexts(values: Sequence[Mapping[str, Any]], maps: Sequence[Mapping[int, int]], selected: Sequence[int], label: str) -> tuple[Any, ...]:
    from mephc.spectral_association import ExternalIsolationContext

    contexts = []
    for index in range(len(values)):
        right = (index + 1) % len(values)
        left_index = [maps[index][branch] for branch in selected]
        right_index = [maps[right][branch] for branch in selected]
        contexts.append(ExternalIsolationContext(
            _excluded(values[index]["raw"].frequencies, left_index),
            _excluded(values[right]["raw"].frequencies, right_index),
            {"source": "RP2 complete six-band excluded spectrum", "level": label, "pair": list(selected)},
        ))
    return tuple(contexts)


def _path_diagnostic(values: Sequence[Mapping[str, Any]], maps: Sequence[Mapping[int, int]], branch: int, thresholds: Any, label: str) -> tuple[Any, Any, dict[str, Any]]:
    from mephc.path_domain import PATH_SINGLE_BAND_QUALIFIED, PATH_SUBSPACE_QUALIFIED, qualify_ordered_path
    from mephc.wilson_geometry import compose_wilson_transport

    frames = [_frame(values[index]["raw"], maps[index][branch], values[index]["record"]["EVALUATED_Q"], 1) for index in range(4)]
    path = qualify_ordered_path(tuple(frames), _contexts(values, maps, [branch], label), thresholds=thresholds, closed=True, provenance={"source": "RP2 associated spectral path", "level": label, "band": branch})
    wilson = compose_wilson_transport(path)
    phase = None if wilson.determinant_phase is None else float(wilson.determinant_phase)
    return path, wilson, {"path_status": path.status, "path_evidence": list(path.evidence), "wilson_status": wilson.status, "wilson_phase_wrapped": phase, "wilson_unitarity_residual": wilson.unitarity_residual}


def _rank1_level(values: Sequence[Mapping[str, Any]], maps: Sequence[Mapping[int, int]], band: int, thresholds: Any, raw_evidence: Sequence[Mapping[str, Any]], stencil: str) -> dict[str, Any]:
    import numpy as np
    from mephc.subspace_transport import parallel_transport_link
    try:
        frames = [_frame(values[index]["raw"], maps[index][band], values[index]["record"]["EVALUATED_Q"], 1) for index in range(4)]
        links = [parallel_transport_link(frames[index], frames[(index + 1) % 4], min_singular_value=1e-12, validation_tolerance=1e-10) for index in range(4)]
        phase = float(np.angle(complex(np.prod([complex(link.unitary[0, 0]) for link in links]))))
        h = 1.0 / float(stencil.split("/")[1])
        return _reported({
            "band_zero_based": band,
            "principal_branch": "(-pi, pi]",
            "association_status": "CLEAR",
            "association_edge_count": len(raw_evidence),
            "association_evidence": list(raw_evidence),
            "transport_method": "solver_neutral_parallel_transport_link",
            "edge_transport": [{"edge": [index, (index + 1) % 4], "overlap_magnitude": float(abs(link.overlap[0, 0])), "min_singular_value": float(link.min_singular_value), "condition_number": float(link.condition_number), "unitarity_residual": float(link.unitarity_residual)} for index, link in enumerate(links)],
            "PHI_RANK1_SHADOW": phase,
            "PLAQUETTE_AREA_Q": h * h,
            "OMEGA_RANK1_SHADOW": float(phase / (h * h)),
            "production_external_gap_context": 0.02,
            "qualification_decision": False,
            "RANK1_RECOVERED": False,
            "DIAGNOSTIC_ONLY": True,
            "REDUCER_ADMISSIBLE": False,
        })
    except (ValueError, RuntimeError) as exc:
        return _unavailable(f"RANK1_SHADOW_TRANSPORT_UNAVAILABLE:{exc}", category="PHYSICAL_OR_NUMERICAL_DIAGNOSTIC")

def _pair_gaps(values: Sequence[Mapping[str, Any]], maps: Sequence[Mapping[int, int]]) -> tuple[float | None, float | None, float | None]:
    below: list[float] = []
    above: list[float] = []
    for index, value in enumerate(values):
        selected = [maps[index][branch] for branch in RANK2]
        pair = [float(value["raw"].frequencies[item]) for item in selected]
        low, high = min(pair), max(pair)
        excluded = [float(x) for item, x in enumerate(value["raw"].frequencies) if item not in selected]
        below.extend(low - item for item in excluded if item < low)
        above.extend(item - high for item in excluded if item > high)
    return (min(below) if below else None, min(above) if above else None, min(below + above) if below or above else None)


def _rank2_level(values: Sequence[Mapping[str, Any]], maps: Sequence[Mapping[int, int]], thresholds: Any, raw_evidence: Sequence[Mapping[str, Any]], contract: Mapping[str, Any]) -> dict[str, Any]:
    try:
        from mephc.path_domain import qualify_ordered_path
        from mephc.wilson_geometry import compose_wilson_transport
        frames = [_frame(values[index]["raw"], maps[index][RANK2[0]], values[index]["record"]["EVALUATED_Q"], 2, selected=[maps[index][branch] for branch in RANK2]) for index in range(4)]
        path = qualify_ordered_path(tuple(frames), _contexts(values, maps, list(RANK2), "L2_RANK2_PAIR"), thresholds=thresholds, closed=True, provenance={"source": "C1 pure associated rank2 pair path", "pair": list(RANK2), "rank1_prerequisite": False})
        wilson = compose_wilson_transport(path)
        overlaps = [edge.overlap for edge in path.edge_results if edge.overlap is not None]
        distances = [edge.cross_k_projector_distance for edge in path.edge_results if edge.cross_k_projector_distance is not None]
        below, above, minimum_external = _pair_gaps(values, maps)
        phase = None if wilson.determinant_phase is None else float(wilson.determinant_phase)
        return _reported({
            "pair_zero_based": list(RANK2), "rank2_pure_path": True, "rank1_prerequisite": False,
            "external_gap_below_pair": below, "external_gap_above_pair": above, "minimum_external_pair_gap": minimum_external,
            "minimum_singular_value": None if not overlaps else min(float(item.min_singular_value) for item in overlaps),
            "principal_angle_diagnostic": None if not overlaps else max(float(item.max_principal_angle) for item in overlaps),
            "projector_distance_diagnostic": None if not distances else max(float(item) for item in distances),
            "rank2_wilson_determinant_phase": phase, "path_status": path.status, "path_evidence": list(path.evidence),
            "wilson_status": wilson.status, "association_status": "CLEAR", "association_evidence": list(raw_evidence),
            "diagnostic_thresholds": dict(contract["rank2_diagnostic_thresholds"]),
            "DIAGNOSTIC_ONLY": True, "REDUCER_ADMISSIBLE": False,
        })
    except (ValueError, RuntimeError) as exc:
        result = _unavailable(f"RANK2_DIAGNOSTIC_UNAVAILABLE:{exc}", category="PHYSICAL_OR_NUMERICAL_DIAGNOSTIC")
        result.update({"pair_zero_based": list(RANK2), "rank2_pure_path": True, "rank1_prerequisite": False})
        return result

def _l3(rank1: Mapping[str, Any], rank3: Mapping[str, Any], rank2: Mapping[str, Any]) -> dict[str, Any]:
    phases = [rank1.get("wilson_phase_wrapped"), rank3.get("wilson_phase_wrapped")]
    determinant = rank2.get("rank2_wilson_determinant_phase")
    if any(value is None for value in (*phases, determinant)):
        return _unavailable("L3_REQUIRES_TWO_RANK1_PHASES_AND_RANK2_DETERMINANT_PHASE")
    value = abs(float(__import__("numpy").angle(__import__("numpy").exp(1j * (float(phases[0]) + float(phases[1]) - float(determinant))))))
    return _reported({
        "metric": "DELTA_PHASE_RANK1SUM_RANK2DET",
        "metric_radians": value,
        "unit": "radians",
        "threshold": None,
        "DIAGNOSTIC_ONLY": True,
    })


def _l0(raw: Any) -> dict[str, Any]:
    full_frequencies = [float(x) for x in raw.frequencies]
    frequencies = [full_frequencies[index] for index in L0_WINDOW]
    gap12 = frequencies[1] - frequencies[0]
    gap23 = frequencies[2] - frequencies[1]
    gap34 = frequencies[3] - frequencies[2]
    sign = "POSITIVE" if gap23 > 0.0 else ("ZERO" if gap23 == 0.0 else "NEGATIVE")
    ordering = "ORDERED" if all(frequencies[index] < frequencies[index + 1] for index in range(3)) else "CROSSING_OR_DEGENERATE"
    return _reported({
        "raw_frequencies_all_six_bands": full_frequencies,
        "l0_window_zero_based": list(L0_WINDOW),
        "ordered_frequencies_bands_1_2_3_4": frequencies,
        "gap_12": gap12, "internal_gap_23": gap23, "upper_external_gap_34": gap34,
        "internal_gap_sign": sign, "band_ordering": ordering,
        "r64_r96_absolute_internal_gap_difference": None, "qualification_decision": False,
    })

def _stencil_entry(center_raw: Any, center_record: Mapping[str, Any], *, center: Sequence[float], stencil: str, provider: Any, preflight: Any, geometry: Mapping[str, Any], background: Any, resolution: int, cache: dict[str, tuple[Any, dict[str, Any]]], identities: Any, counters: dict[str, int], raw_thresholds: Any, thresholds: Any, execution: Mapping[str, Any]) -> dict[str, Any]:
    from mephc.valley_benchmark import centered_ccw_plaquette_requests
    h = 1.0 / int(stencil.split("/")[1])
    requests = centered_ccw_plaquette_requests((tuple(center),), h, period_basis=preflight.public_period_basis, coordinate_mapping_digest=preflight.mapping_digest)
    values = []
    for request in requests:
        raw, record = _solve_point(provider, preflight, geometry, background, nominal_q=request.nominal_vertex_q, manifest_q=request.canonical_periodic_vertex_q, resolution=resolution, cache=cache, identities=identities, counters=counters)
        values.append({"raw": raw, "record": record, "gram_diagnostics": _gram_diagnostics(raw)})
    try:
        maps, association = _associate_vertices(values, raw_thresholds)
    except DiagnosticAdapterPreconditionError:
        raise
    except (ValueError, RuntimeError) as exc:
        l1 = {str(band): _unavailable(f"RANK1_ASSOCIATION_UNAVAILABLE:{exc}") for band in ZERO_BANDS}
        l2 = _unavailable(f"RANK2_ASSOCIATION_UNAVAILABLE:{exc}")
        l3 = _unavailable(f"L3_ASSOCIATION_UNAVAILABLE:{exc}")
        association = [{"status": "NOT_AVAILABLE_WITH_REASON", "reason": str(exc), "unavailability_class": "PHYSICAL_OR_NUMERICAL_DIAGNOSTIC", "candidate_window_zero_based": list(ASSOCIATION_WINDOW)}]
    else:
        l1 = {str(band): _rank1_level(values, maps, band, thresholds, association, stencil) for band in ZERO_BANDS}
        l2 = _rank2_level(values, maps, thresholds, association, execution)
        l3 = _l3(l1["2"], l1["3"], l2)
    return {
        "stencil": stencil, "NOMINAL_Q": [float(x) for x in center], "MANIFEST_Q": [float(x) for x in center],
        "L0": _l0(center_raw), "L1": l1, "L2": l2, "L3": l3, "association": association,
        "association_candidate_window_zero_based": list(ASSOCIATION_WINDOW),
        "gram_diagnostics": [item["gram_diagnostics"] for item in values],
        "vertex_sampling": [item["record"] for item in values], "center_sampling": dict(center_record),
        "DIAGNOSTIC_ONLY": True, "REDUCER_ADMISSIBLE": False,
    }

def compute_worker(root: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    """Native child body; this function is never imported by the parent path."""
    import meep as mp
    from audit.e9c.run_k_kprime_rank1_berry import build_inputs, geometry_inputs, make_provider
    from mephc.spectral_association import RawAssociationThresholds, SubspaceQualificationThresholds
    from mephc.valley_benchmark import PhysicalSolveCache

    execution = load_execution_contract(root)
    policy = load_policy(root)
    geometry = geometry_inputs()
    preflight, lattice, solver_geometry, background = build_inputs(geometry)
    provider = make_provider(int(row["resolution"]), lattice, solver_geometry, background)
    cfg=execution["raw_association"]
    raw_thresholds=RawAssociationThresholds(probability_threshold=float(cfg["probability_threshold"]),margin_threshold=float(cfg["margin_threshold"]),assignment_margin_threshold=float(cfg["assignment_margin_threshold"]),validation_tolerance=float(cfg["validation_tolerance"]))
    diagnostic = execution["rank2_diagnostic_thresholds"]
    thresholds = SubspaceQualificationThresholds(
        min_singular_value=float(diagnostic["MIN_SIGMA"]),
        max_principal_angle=float(diagnostic["MAX_PRINCIPAL_ANGLE"]),
        max_projector_distance=float(diagnostic["MAX_PROJECTOR_DISTANCE"]),
        min_external_gap=float(diagnostic["MIN_EXTERNAL_PAIR_GAP"]),
    )
    cache: dict[str, tuple[Any, dict[str, Any]]] = {}
    identities = PhysicalSolveCache()
    counters = {"solver_requests": 0, "cache_hits": 0, "solver_failures": 0}
    center = tuple(float(x) for x in row["authoritative_coordinate"])
    center_raw, center_record = _solve_point(provider, preflight, geometry, background, nominal_q=center, manifest_q=center, resolution=int(row["resolution"]), cache=cache, identities=identities, counters=counters)
    entries = {
        stencil: _stencil_entry(center_raw, center_record, center=center, stencil=stencil, provider=provider, preflight=preflight, geometry=geometry, background=background, resolution=int(row["resolution"]), cache=cache, identities=identities, counters=counters, raw_thresholds=raw_thresholds, thresholds=thresholds, execution=execution)
        for stencil in STENCILS
    }
    result = {
        "schema": WORKER_SCHEMA,
        "work_order_id": WORK_ORDER,
        "phase": PHASE,
        "worker_id": row["sample_id"],
        "source_sample_id": row["source_sample_id"],
        "source_sample_index": row["source_sample_index"],
        "sample_index": row["sample_index"],
        "resolution": row["resolution"],
        "authoritative_coordinate": list(row["authoritative_coordinate"]),
        "worker_coordinate": list(center),
        "execution_git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "stencils": entries,
        "matrix_entry_count": len(entries),
        "counters": counters,
        "native_import_confirmed": "meep" in sys.modules,
        "child_pid": os.getpid(),
        "diagnostic_only": True,
        "reducer_admissible": False,
        "no_band2_recovery": True,
        "no_berry_or_chern": True,
        "no_three_band_sum": True,
        "no_source_anchor": True,
        "policy_sample_ids_derived": True,
        "policy_contract_sha256": sha256_file(root / POLICY_REL),
        "policy_canonical_semantic_sha256": execution["policy_contract"]["canonical_semantic_sha256"],
        "original_rp2_execution_sha": ORIGINAL_RP2_EXECUTION_SHA,
        "association_candidate_window_zero_based": list(ASSOCIATION_WINDOW),
    }
    validate_worker_payload(result, row)
    return result


def validate_worker_payload(payload: Mapping[str, Any], row: Mapping[str, Any]) -> None:
    required = {
        "schema": WORKER_SCHEMA, "work_order_id": WORK_ORDER, "phase": PHASE,
        "worker_id": row["sample_id"], "source_sample_id": row["source_sample_id"],
        "source_sample_index": row["source_sample_index"], "sample_index": row["sample_index"],
        "resolution": row["resolution"], "authoritative_coordinate": row["authoritative_coordinate"],
        "worker_coordinate": row["authoritative_coordinate"], "matrix_entry_count": 2,
        "diagnostic_only": True, "reducer_admissible": False, "policy_sample_ids_derived": True,
        "association_candidate_window_zero_based": list(ASSOCIATION_WINDOW),
    }
    for key, expected in required.items():
        if _json_value(payload.get(key)) != _json_value(expected):
            raise CampaignRuntimeError(f"RP2_C1_WORKER_PAYLOAD_{key.upper()}_MISMATCH")
    if set(payload.get("stencils", {})) != set(STENCILS):
        raise CampaignRuntimeError("RP2_C1_WORKER_STENCIL_COVERAGE_MISMATCH")
    for stencil in STENCILS:
        entry=payload["stencils"][stencil]
        if entry.get("stencil") != stencil or entry.get("DIAGNOSTIC_ONLY") is not True or entry.get("REDUCER_ADMISSIBLE") is not False:
            raise CampaignRuntimeError(f"RP2_C1_ENTRY_SCHEMA_MISMATCH:{stencil}")
        if entry.get("association_candidate_window_zero_based") != list(ASSOCIATION_WINDOW) or len(entry.get("gram_diagnostics", [])) != 4:
            raise CampaignRuntimeError(f"RP2_C1_ENTRY_DIAGNOSTIC_COVERAGE_MISMATCH:{stencil}")
        for level in ("L0","L1","L2","L3"):
            values=list(entry[level].values()) if level=="L1" and isinstance(entry[level], Mapping) else [entry[level]]
            for item in values:
                if not isinstance(item, Mapping) or item.get("status") not in {"DIAGNOSTIC_REPORTED","NOT_AVAILABLE_WITH_REASON"}:
                    raise CampaignRuntimeError(f"RP2_C1_LEVEL_COVERAGE_MISSING:{stencil}:{level}")
                if item["status"]=="NOT_AVAILABLE_WITH_REASON" and (not item.get("reason") or item.get("unavailability_class") not in {"PHYSICAL_OR_NUMERICAL_DIAGNOSTIC","ADAPTER_OR_API_PRECONDITION_FAILURE"}):
                    raise CampaignRuntimeError(f"RP2_C1_LEVEL_REASON_MISSING:{stencil}:{level}")
        if entry["L2"].get("status")=="DIAGNOSTIC_REPORTED" and (entry["L2"].get("pair_zero_based") != list(RANK2) or entry["L2"].get("rank1_prerequisite") is not False):
            raise CampaignRuntimeError(f"RP2_C1_L2_NOT_PURE_RANK2:{stencil}")
        for item in entry["L1"].values():
            if item.get("status")=="DIAGNOSTIC_REPORTED" and item.get("RANK1_RECOVERED") is not False:
                raise CampaignRuntimeError(f"RP2_C1_L1_RECOVERY_FIREWALL:{stencil}")
    forbidden={"BAND2_SAMPLE_QUALIFIED_FOR_REDUCER","numeric_band2_chern","partial_band2_chern","three_band_sum","CONSISTENCY_PASSED"}
    if forbidden & set(str(key) for key in payload):
        raise CampaignRuntimeError("RP2_C1_REDUCER_OR_CONSISTENCY_FORBIDDEN_OUTPUT")

def _canary_gate(payload: Mapping[str, Any], row: Mapping[str, Any]) -> dict[str, Any]:
    if row["source_sample_id"] != "fr=0;grid_i=-34;grid_j=-17;estimator=SOURCE_GRID" or int(row["resolution"]) != 64:
        raise CampaignRuntimeError("RP2_C1_CANARY_ROW_ID_MISMATCH")
    association_reached=False; rank2_reached=False
    for stencil in STENCILS:
        entry=payload["stencils"][stencil]
        if entry.get("association_candidate_window_zero_based") != list(ASSOCIATION_WINDOW):
            raise CampaignRuntimeError("RP2_C1_CANARY_ASSOCIATION_WINDOW_MISMATCH")
        for item in entry.get("association", []):
            if item.get("unavailability_class")=="ADAPTER_OR_API_PRECONDITION_FAILURE":
                raise CampaignRuntimeError("RP2_C1_CANARY_ADAPTER_PRECONDITION_FAILURE")
            association_reached = association_reached or item.get("status") in {"CLEAR","AMBIGUOUS","INCOMPLETE","NOT_AVAILABLE_WITH_REASON"}
        l2=entry.get("L2",{})
        rank2_reached = rank2_reached or l2.get("pair_zero_based")==list(RANK2)
    if not association_reached or not rank2_reached:
        raise CampaignRuntimeError("RP2_C1_CANARY_DIAGNOSTIC_PATH_NOT_REACHED")
    return {"passed":True,"worker_id":row["sample_id"],"resolution":64,"stencils":list(STENCILS),"association_candidate_window_zero_based":list(ASSOCIATION_WINDOW),"rank2_pair_zero_based":list(RANK2),"adapter_precondition_failure":False,"workers_released_after_canary":11}


def run_parent(root: Path, runtime_root: Path) -> dict[str, Any]:
    assert_parent_solver_free()
    execution=load_execution_contract(root); rows=build_plan(root)
    execution_sha=subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip()
    runner=root/"audit/e9f/run_e9f_c1_rp2_c1.py"; contract_path=root/CONTRACT_REL
    plan_id=semantic_plan_fingerprint(rows,estimator_id="E9F_C1_RP2_C1_DIAGNOSTIC",semantic_domain_id="RP1_FIXED_SIX_LOW_GAP_POINTS",spacing_id="1/72_AND_1/144")
    identity=CampaignIdentity(execution_sha,sha256_file(runner),sha256_file(contract_path),plan_id,tuple(row["sample_id"] for row in rows),expected_sample_indices=tuple(row["sample_index"] for row in rows),semantic_estimator_id="E9F_C1_RP2_C1_DIAGNOSTIC",semantic_domain_id="RP1_FIXED_SIX_LOW_GAP_POINTS",semantic_spacing_id="1/72_AND_1/144")
    CampaignRuntime.ARTIFACT_SCHEMA=WORKER_SCHEMA
    runtime=CampaignRuntime(Path(runtime_root),identity,runner_path=runner,contract_path=contract_path,repository_path=root,remote_name="origin",remote_ref="refs/heads/sandbox",production_mode=True)
    preflight=runtime.preflight(plan_rows=rows); assert_parent_solver_free()
    measurements=[]; rss_series=[]
    def worker(row):
        before=current_rss_kib()
        payload,measurement=run_reaped_child(worker_command(root,row),str(row["sample_id"]))
        validate_worker_payload(payload,row); after=current_rss_kib()
        measurement=dict(measurement); measurement.update({"parent_rss_before_kib":before,"parent_rss_after_kib":after})
        measurements.append(measurement); rss_series.append({"worker_id":row["sample_id"],"before_kib":before,"after_kib":after})
        return {**payload,"process_measurement":measurement}
    row0=rows[0]; canary_payload=worker(row0); canary=_canary_gate(canary_payload,row0)
    runtime.publish_worker_artifact(sample_id=row0["sample_id"],sample_index=int(row0["sample_index"]),result=canary_payload)
    runtime.write_checkpoint({row0["sample_id"]})
    run_status=runtime.run(rows,worker); assert_parent_solver_free()
    result={"schema":RESULT_SCHEMA,"work_order_id":WORK_ORDER,"phase":PHASE,"stop_after":STOP_AFTER,"execution_identity":identity.as_dict(),"original_rp2_execution_sha":ORIGINAL_RP2_EXECUTION_SHA,"preflight":preflight,"canary":canary,"run_status":run_status,"worker_count":len(rows),"matrix_entry_count":len(rows)*len(STENCILS),"process_measurements":measurements,"parent_rss_series_kib":rss_series,"parent_native_import_free":True,"orphan_native_child_count":sum(item["orphan_count"] for item in measurements),"all_worker_rows_present":len(measurements)==len(rows),"diagnostic_only":True,"reducer_admissible":False,"no_band2_recovery":True,"no_berry_or_chern":True,"no_three_band_sum":True,"no_source_anchor":True,"main_push_authorized":False,"rp3_authorized":False}
    if result["orphan_native_child_count"]!=0 or not result["all_worker_rows_present"]: raise CampaignRuntimeError("RP2_C1_PROCESS_OR_COVERAGE_FAIL_CLOSED")
    (Path(runtime_root)/"rp2_c1_result.json").write_text(json.dumps(result,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":run_status["status"],"worker_count":len(rows),"matrix_entry_count":len(rows)*len(STENCILS),"canary_passed":canary["passed"]},sort_keys=True),flush=True)
    return result

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--runtime-root", default=None)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--worker-id")
    parser.add_argument("--resolution", type=int)
    parser.add_argument("--coordinate-json")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.self_check:
        rows = build_plan(root)
        assert_parent_solver_free()
        print(json.dumps({"self_check": "PASSED", "logical_worker_count": len(rows), "matrix_entry_count": len(rows) * len(STENCILS)}, sort_keys=True))
        return 0
    if args.worker:
        if args.worker_id is None or args.resolution is None or args.coordinate_json is None:
            parser.error("worker mode requires worker-id, resolution, and coordinate-json")
        row = _row_by_worker_id(root, args.worker_id)
        coordinate = json.loads(args.coordinate_json)
        validate_worker_identity(row, worker_id=args.worker_id, resolution=args.resolution, coordinate=coordinate)
        with contextlib.redirect_stdout(sys.stderr):
            payload = compute_worker(root, row)
        print(json.dumps(payload, sort_keys=True, allow_nan=False), flush=True)
        return 0
    runtime_root = Path(args.runtime_root) if args.runtime_root else root / "audit/e9f/rp2_c1_runtime"
    run_parent(root, runtime_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
