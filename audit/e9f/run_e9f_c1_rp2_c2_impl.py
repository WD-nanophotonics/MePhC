"""E9F.C1.RP2.C2 bounded Maxwell representation Gram/association probe."""
from __future__ import annotations
import argparse
import contextlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence

from audit.e9f import run_e9f_c1_rp2_c1_impl as base
from audit.infrastructure.campaign_runtime import CampaignIdentity, CampaignRuntime, CampaignRuntimeError, current_rss_kib, semantic_plan_fingerprint

WORK_ORDER = "TRILATT-E9F-C1-RP2-C2-20260824-233"
PHASE = "E9F.C1.RP2.C2"
STOP_AFTER = "E9F_C1_RP2_C2_REPORT"
CONTRACT_REL = Path("audit/e9f/rp2_c2_execution_contract.json")
POLICY_REL = base.POLICY_REL
RUNNER_MARKER = "run_e9f_c1_rp2_c2.py"
WORKER_SCHEMA = "trilatt_e9f_c1_rp2_c2_worker_v1"
RESULT_SCHEMA = "trilatt_e9f_c1_rp2_c2_result_v1"
BASE_SHA = "99e37c05f9026e4fcd02eba6dc0060c6656b1b22"
EXECUTION_SHA_EXPECTED = "PENDING_COMMIT"
RP1_POLICY_SHA = "75f2d32853ab7e0a5878c19a732f4ac91ef993c105a8000b87e4a8a6ed6d5145"
RP1_POLICY_CANONICAL_SHA = "cfbe71ff9f648048901038823c25ffd358bb8a80394fe05d082a57957acfc84a"
PRIMARY_SAMPLE_ID = "fr=0;grid_i=-34;grid_j=-17;estimator=SOURCE_GRID"
CONTROL_Q_PUBLIC = (2.0 / 3.0, 0.0)
RESOLUTIONS = (64, 96)
STENCILS = ("1/72", "1/144")
PAIR = (2, 3)
ASSOCIATION_THRESHOLD = {"probability_threshold": 0.5, "margin_threshold": 0.05, "assignment_margin_threshold": 0.05, "validation_tolerance": 1e-10}
GRAM_DECOMPOSITION_CLOSURE_TOL = 1e-12
FREQUENCY_REPLAY_TOL = 1e-8


def _json(value: Any) -> Any:
    return base._json_value(value)


def _pair_complex(matrix: Any, i: int = 2, j: int = 3) -> dict[str, Any]:
    z = complex(matrix[i, j])
    return {"real": float(z.real), "imag": float(z.imag), "magnitude": float(abs(z))}


def _finite_or_none(value: float) -> float | None:
    return float(value) if math.isfinite(float(value)) else None


def load_execution_contract(root: Path) -> dict[str, Any]:
    value = json.loads((root / CONTRACT_REL).read_text(encoding="utf-8"))
    if value.get("schema") != "trilatt_e9f_c1_rp2_c2_execution_contract_v1":
        raise CampaignRuntimeError("RP2_C2_CONTRACT_SCHEMA_MISMATCH")
    if value.get("work_order_id") != WORK_ORDER or value.get("phase") != PHASE:
        raise CampaignRuntimeError("RP2_C2_CONTRACT_WORK_ORDER_MISMATCH")
    if value.get("primary", {}).get("sample_id") != PRIMARY_SAMPLE_ID:
        raise CampaignRuntimeError("RP2_C2_PRIMARY_SAMPLE_MISMATCH")
    if value.get("primary", {}).get("resolutions") != list(RESOLUTIONS) or value.get("primary", {}).get("stencils") != list(STENCILS):
        raise CampaignRuntimeError("RP2_C2_PRIMARY_SCOPE_MISMATCH")
    if value.get("primary", {}).get("total_solves_per_resolution") != 9 or value.get("control", {}).get("total_solves") != 2:
        raise CampaignRuntimeError("RP2_C2_SOLVE_SCOPE_MISMATCH")
    if value.get("association", {}).get("thresholds") != ASSOCIATION_THRESHOLD:
        raise CampaignRuntimeError("RP2_C2_ASSOCIATION_THRESHOLDS_MUTATED")
    if value.get("gram", {}).get("decomposition_closure_tolerance") != GRAM_DECOMPOSITION_CLOSURE_TOL:
        raise CampaignRuntimeError("RP2_C2_GRAM_CLOSURE_TOLERANCE_MUTATED")
    if value.get("scientific_firewall", {}).get("diagnostic_only") is not True or value.get("scientific_firewall", {}).get("berry_or_wilson") is not False:
        raise CampaignRuntimeError("RP2_C2_SCIENTIFIC_FIREWALL_MUTATED")
    return value


def load_policy(root: Path) -> dict[str, Any]:
    return base.load_policy(root)


def build_plan(root: Path) -> list[dict[str, Any]]:
    policy = load_policy(root)
    records = {row["sample_id"]: row for row in policy["immutable_inputs"]["failed_sample_records"]}
    sample = records.get(PRIMARY_SAMPLE_ID)
    if sample is None:
        raise CampaignRuntimeError("RP2_C2_PRIMARY_SAMPLE_NOT_IN_POLICY")
    rows = []
    for index, resolution in enumerate(RESOLUTIONS):
        rows.append({
            "sample_id": f"{PRIMARY_SAMPLE_ID}::resolution={resolution}",
            "source_sample_id": PRIMARY_SAMPLE_ID,
            "source_sample_index": int(sample["sample_index"]),
            "sample_index": index,
            "resolution": int(resolution),
            "authoritative_coordinate": [float(x) for x in sample["center"]],
            "control_q_public": list(CONTROL_Q_PUBLIC),
        })
    return rows


def validate_worker_identity(row: Mapping[str, Any], *, worker_id: str, resolution: int, coordinate: Sequence[float]) -> None:
    if worker_id != row["sample_id"] or int(resolution) != int(row["resolution"]) or list(map(float, coordinate)) != list(row["authoritative_coordinate"]):
        raise CampaignRuntimeError("RP2_C2_WORKER_IDENTITY_MISMATCH")


def assert_parent_solver_free() -> None:
    base.assert_parent_solver_free()


def _proc_cmdline(pid: int) -> str:
    try:
        return (Path("/proc") / str(pid) / "cmdline").read_bytes().replace(b"\x00", b" ").decode(errors="replace")
    except (OSError, UnicodeError):
        return ""


def scan_worker_processes(worker_id: str | None = None) -> list[int]:
    if not Path("/proc").is_dir():
        raise CampaignRuntimeError("RP2_C2_ORPHAN_INSPECTION_UNAVAILABLE")
    found = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            command = _proc_cmdline(int(entry.name))
            if RUNNER_MARKER in command and "--worker" in command and (worker_id is None or worker_id in command):
                found.append(int(entry.name))
    return sorted(found)


def run_reaped_child(command: Sequence[str], worker_id: str, *, timeout_seconds: float = 900.0) -> tuple[dict[str, Any], dict[str, Any]]:
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        process.kill()
        process.communicate()
        raise CampaignRuntimeError(f"RP2_C2_NATIVE_CHILD_TIMEOUT:{worker_id}") from exc
    measurement = {
        "worker_id": worker_id, "launched_pid": int(process.pid), "returncode": int(process.returncode),
        "direct_pid_gone": not (Path("/proc") / str(process.pid)).exists(),
        "orphan_pids": [pid for pid in scan_worker_processes(worker_id) if pid != process.pid],
    }
    measurement["orphan_count"] = len(measurement["orphan_pids"])
    if not measurement["direct_pid_gone"] or measurement["orphan_count"]:
        raise CampaignRuntimeError(f"RP2_C2_NATIVE_ORPHAN_DETECTED:{measurement}")
    if process.returncode != 0:
        raise CampaignRuntimeError(f"RP2_C2_NATIVE_CHILD_FAILED:{worker_id}:{process.returncode}:{stderr[-1000:]}")
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise CampaignRuntimeError(f"RP2_C2_NATIVE_CHILD_JSON_INVALID:{worker_id}:{stderr[-1000:]}") from exc
    return payload, measurement


def worker_command(root: Path, row: Mapping[str, Any]) -> list[str]:
    return [sys.executable, str(root / "audit/e9f/run_e9f_c1_rp2_c2.py"), "--worker", "--root", str(root), "--worker-id", str(row["sample_id"]), "--resolution", str(row["resolution"]), "--coordinate-json", json.dumps(row["authoritative_coordinate"], separators=(",", ":"))]


def _split_vector(vector: Any) -> tuple[Any, Any]:
    import numpy as np
    value = np.asarray(vector, dtype=np.complex128)
    if value.ndim != 1 or value.size == 0 or value.size % 2:
        raise ValueError("E9F_C1_RP2_C2_VECTOR_SPLIT_DIMENSION_INVALID")
    half = value.size // 2
    return value[:half], value[half:]


def _unit(vector: Any) -> tuple[Any, float]:
    import numpy as np
    value = np.asarray(vector, dtype=np.complex128)
    norm = float(np.linalg.norm(value))
    if not math.isfinite(norm) or norm <= 0.0:
        raise ValueError("E9F_C1_RP2_C2_COMPONENT_NORM_INVALID")
    return value / norm, norm * norm


def _raw_states(raw: Any, representation: str) -> list[Any]:
    from mephc.eigenspace import RawEigenstate
    states = []
    for index in PAIR:
        vector = raw.normalized_vectors[index]
        if representation == "E_ONLY":
            vector, _ = _unit(_split_vector(vector)[0])
        elif representation == "H_ONLY":
            vector, _ = _unit(_split_vector(vector)[1])
        elif representation != "COMBINED_EH":
            raise ValueError("RP2_C2_UNKNOWN_REPRESENTATION")
        states.append(RawEigenstate(tuple(float(x) for x in raw.k_point), index, float(raw.frequencies[index]), vector, {"diagnostic_representation": representation}))
    return states


def _point_metrics(raw: Any, record: Mapping[str, Any], replay: Mapping[tuple[float, ...], Sequence[float]] | None = None) -> dict[str, Any]:
    import numpy as np
    vectors = np.column_stack([np.asarray(item, dtype=np.complex128) for item in raw.normalized_vectors])
    e_columns = []
    h_columns = []
    e_norms = []
    h_norms = []
    e_unit_columns = []
    h_unit_columns = []
    for vector in raw.normalized_vectors:
        e_part, h_part = _split_vector(vector)
        e_unit, e_norm = _unit(e_part)
        h_unit, h_norm = _unit(h_part)
        e_columns.append(e_part)
        h_columns.append(h_part)
        e_norms.append(e_norm)
        h_norms.append(h_norm)
        e_unit_columns.append(e_unit)
        h_unit_columns.append(h_unit)
    e_matrix = np.column_stack(e_columns)
    h_matrix = np.column_stack(h_columns)
    g_eh = vectors.conj().T @ vectors
    g_e = e_matrix.conj().T @ e_matrix
    g_h = h_matrix.conj().T @ h_matrix
    g_e_unit = np.column_stack(e_unit_columns).conj().T @ np.column_stack(e_unit_columns)
    g_h_unit = np.column_stack(h_unit_columns).conj().T @ np.column_stack(h_unit_columns)
    closure = float(np.max(np.abs(g_eh - g_e - g_h)))
    pair_eh = np.asarray(g_eh[np.ix_(PAIR, PAIR)], dtype=np.complex128)
    pair_eh_h = (pair_eh + pair_eh.conj().T) / 2.0
    eigenvalues = [float(value) for value in np.linalg.eigvalsh(pair_eh_h)]
    minimum = min(abs(value) for value in eigenvalues)
    condition = _finite_or_none(max(abs(value) for value in eigenvalues) / minimum) if minimum > 0.0 else None
    determinant = complex(np.linalg.det(pair_eh))
    replay_record = None
    replay_key = tuple(float(x) for x in record["MANIFEST_Q"])
    if replay is not None and replay_key in replay:
        prior = [float(x) for x in replay[replay_key]]
        current = [float(x) for x in raw.frequencies]
        replay_record = {
            "matched": True,
            "prior_frequencies_all6": prior,
            "max_abs_difference": float(max(abs(a - b) for a, b in zip(current, prior))),
            "tolerance": FREQUENCY_REPLAY_TOL,
        }
    else:
        replay_record = {"matched": False, "prior_frequencies_all6": None, "max_abs_difference": None, "tolerance": FREQUENCY_REPLAY_TOL}
    return {
        "NOMINAL_Q": list(record["NOMINAL_Q"]),
        "MANIFEST_Q": list(record["MANIFEST_Q"]),
        "EVALUATED_Q": list(record["EVALUATED_Q"]),
        "physical_cache_identity": record["physical_cache_identity"],
        "RAW_FREQUENCIES_ALL6": [float(x) for x in raw.frequencies],
        "FULL6_PROVIDER_ORTHOGONALITY_STATUS": str(raw.orthogonality_status),
        "FULL6_PROVIDER_MAX_OFFDIAG_GRAM": float(raw.max_off_diagonal_gram),
        "FULL6_PROVIDER_MAX_NORMALIZATION_ERROR": float(raw.max_normalization_error),
        "PAIR_G_EH_23": _pair_complex(g_eh),
        "PAIR_G_E_CONTRIB_23": _pair_complex(g_e),
        "PAIR_G_H_CONTRIB_23": _pair_complex(g_h),
        "PAIR_G_E_UNIT_23": _pair_complex(g_e_unit),
        "PAIR_G_H_UNIT_23": _pair_complex(g_h_unit),
        "PAIR_G_EH_EIGENVALUES": eigenvalues,
        "PAIR_G_EH_CONDITION_NUMBER": condition,
        "PAIR_G_EH_DETERMINANT": {"real": float(determinant.real), "imag": float(determinant.imag), "magnitude": float(abs(determinant))},
        "E_COMPONENT_NORM_SQUARED": [float(e_norms[index]) for index in PAIR],
        "H_COMPONENT_NORM_SQUARED": [float(h_norms[index]) for index in PAIR],
        "E_PLUS_H_NORM_SQUARED_SUM": [float(e_norms[index] + h_norms[index]) for index in PAIR],
        "TARGET_PAIR_GAP_F3_MINUS_F2": float(raw.frequencies[3] - raw.frequencies[2]),
        "GRAM_DECOMPOSITION_CLOSURE_MAX": closure,
        "GRAM_DECOMPOSITION_CLOSURE_TOL": GRAM_DECOMPOSITION_CLOSURE_TOL,
        "GRAM_DECOMPOSITION_CLOSURE_PASS": bool(closure <= GRAM_DECOMPOSITION_CLOSURE_TOL),
        "replay": replay_record,
    }


def _association_probe(vertices: Sequence[Mapping[str, Any]], representation: str) -> dict[str, Any]:
    from mephc.spectral_association import RawAssociationThresholds, associate_raw_states
    thresholds = RawAssociationThresholds(**ASSOCIATION_THRESHOLD)
    maps = [{2: 2, 3: 3}]
    edges = []
    for index in range(4):
        right = (index + 1) % 4
        left_raw = vertices[index]["raw"]
        right_raw = vertices[right]["raw"]
        left_states = [_raw_states(left_raw, representation)[0 if branch == 2 else 1] for branch in (maps[index][2], maps[index][3])]
        right_states = _raw_states(right_raw, representation)
        try:
            association = associate_raw_states(left_states, right_states, thresholds=thresholds)
        except (TypeError, ValueError, RuntimeError) as exc:
            edges.append({
                "edge": [index, right], "representation": representation,
                "precondition_status": "FAIL", "association_status": "NOT_RUN",
                "matched_by_solver_index": None, "matched_probabilities": None,
                "row_margins": None, "column_margins": None, "global_assignment_margin": None,
                "failure_reason": str(exc), "thresholds": dict(ASSOCIATION_THRESHOLD),
            })
            maps.append(dict(maps[index]))
            continue
        edge = {
            "edge": [index, right], "representation": representation,
            "precondition_status": "PASS", "association_status": association.status,
            "matched_by_solver_index": [list(pair) for pair in association.matched_by_solver_index],
            "matched_probabilities": list(association.matched_probabilities),
            "row_margins": list(association.row_margins), "column_margins": list(association.column_margins),
            "global_assignment_margin": association.global_assignment_margin,
            "failure_reason": None if association.status == "CLEAR" else "; ".join(association.evidence),
            "thresholds": dict(ASSOCIATION_THRESHOLD),
        }
        edges.append(edge)
        if association.status == "CLEAR":
            mapping = dict(association.matched_by_solver_index)
            maps.append({branch: mapping[maps[index][branch]] for branch in (2, 3)})
        else:
            maps.append(dict(maps[index]))
    clear = sum(edge["association_status"] == "CLEAR" for edge in edges)
    precondition_pass = sum(edge["precondition_status"] == "PASS" for edge in edges)
    closure = bool(clear == 4 and len(maps) == 5 and maps[4] == maps[0])
    return {
        "representation": representation, "edges": edges,
        "precondition_pass_edges": precondition_pass, "clear_edges": clear,
        "ASSOCIATION_LOOP_CLOSURE": closure if clear == 4 else None,
        "propagated_maps": maps if clear == 4 else None,
    }


def _load_replay_index(root: Path, resolution: int) -> dict[tuple[float, ...], Sequence[float]]:
    result: dict[tuple[float, ...], Sequence[float]] = {}
    directory = root / "audit/e9f/rp2_evidence/workers"
    for path in sorted(directory.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("source_sample_id") != PRIMARY_SAMPLE_ID or int(payload.get("resolution", -1)) != int(resolution):
            continue
        for entry in payload.get("stencils", {}).values():
            records = [entry.get("center_sampling", {}), *entry.get("vertex_sampling", [])]
            for record in records:
                if record.get("MANIFEST_Q") and record.get("frequencies"):
                    result[tuple(float(x) for x in record["MANIFEST_Q"])] = [float(x) for x in record["frequencies"]]
    return result


def _probe_stencil(center: Sequence[float], stencil: str, provider: Any, preflight: Any, geometry: Mapping[str, Any], background: Any, resolution: int, cache: dict[str, Any], identities: Any, counters: dict[str, int], replay: Mapping[tuple[float, ...], Sequence[float]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from mephc.valley_benchmark import centered_ccw_plaquette_requests
    h = 1.0 / int(stencil.split("/")[1])
    requests = centered_ccw_plaquette_requests((tuple(center),), h, period_basis=preflight.public_period_basis, coordinate_mapping_digest=preflight.mapping_digest)
    vertices = []
    for request in requests:
        raw, record = base._solve_point(provider, preflight, geometry, background, nominal_q=request.nominal_vertex_q, manifest_q=request.canonical_periodic_vertex_q, resolution=resolution, cache=cache, identities=identities, counters=counters)
        vertices.append({"raw": raw, "metrics": _point_metrics(raw, record, replay)})
    probes = {name: _association_probe(vertices, name) for name in ("COMBINED_EH", "E_ONLY", "H_ONLY")}
    agreement = sum(
        1 for left, right in zip(probes["E_ONLY"]["edges"], probes["H_ONLY"]["edges"])
        if left["association_status"] == "CLEAR" and right["association_status"] == "CLEAR"
        and left["matched_by_solver_index"] == right["matched_by_solver_index"]
    )
    return [item["metrics"] for item in vertices], {
        "stencil": stencil, "vertices": [item["metrics"] for item in vertices],
        "association": probes, "E_H_ASSIGNMENT_AGREEMENT_EDGE_COUNT": agreement,
    }


def compute_worker(root: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    import meep as mp  # noqa: F401
    from audit.e9c.run_k_kprime_rank1_berry import build_inputs, geometry_inputs, make_provider
    from mephc.valley_benchmark import PhysicalSolveCache

    execution = load_execution_contract(root)
    policy = load_policy(root)
    geometry = geometry_inputs()
    preflight, lattice, solver_geometry, background = build_inputs(geometry)
    provider = make_provider(int(row["resolution"]), lattice, solver_geometry, background)
    sample = next(item for item in policy["immutable_inputs"]["failed_sample_records"] if item["sample_id"] == PRIMARY_SAMPLE_ID)
    center = tuple(float(x) for x in sample["center"])
    cache: dict[str, Any] = {}
    identities = PhysicalSolveCache()
    counters = {"solver_requests": 0, "cache_hits": 0, "solver_failures": 0}
    replay = _load_replay_index(root, int(row["resolution"]))
    center_raw, center_record = base._solve_point(provider, preflight, geometry, background, nominal_q=center, manifest_q=center, resolution=int(row["resolution"]), cache=cache, identities=identities, counters=counters)
    center_metrics = _point_metrics(center_raw, center_record, replay)
    stencils = {}
    all_metrics = [center_metrics]
    for stencil in STENCILS:
        metrics, entry = _probe_stencil(center, stencil, provider, preflight, geometry, background, int(row["resolution"]), cache, identities, counters, replay)
        all_metrics.extend(metrics)
        stencils[stencil] = entry
    control_raw, control_record = base._solve_point(provider, preflight, geometry, background, nominal_q=CONTROL_Q_PUBLIC, manifest_q=CONTROL_Q_PUBLIC, resolution=int(row["resolution"]), cache=cache, identities=identities, counters=counters)
    control_metrics = _point_metrics(control_raw, control_record, None)
    closure_failures = [
        {"NOMINAL_Q": item["NOMINAL_Q"], "MEASURED_VALUE": item["GRAM_DECOMPOSITION_CLOSURE_MAX"], "THRESHOLD_VALUE": GRAM_DECOMPOSITION_CLOSURE_TOL}
        for item in all_metrics if not item["GRAM_DECOMPOSITION_CLOSURE_PASS"]
    ]
    result = {
        "schema": WORKER_SCHEMA, "work_order_id": WORK_ORDER, "phase": PHASE,
        "worker_id": row["sample_id"], "source_sample_id": PRIMARY_SAMPLE_ID,
        "source_sample_index": int(row["source_sample_index"]), "sample_index": int(row["sample_index"]),
        "resolution": int(row["resolution"]), "authoritative_coordinate": list(row["authoritative_coordinate"]),
        "execution_git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
        "primary": {"center": center_metrics, "stencils": stencils, "primary_solve_count": len(all_metrics)},
        "control": {"CONTROL_Q_PUBLIC": list(CONTROL_Q_PUBLIC), "center": control_metrics, "solve_count": 1},
        "counters": counters, "native_import_confirmed": "meep" in sys.modules, "child_pid": os.getpid(),
        "closure_failures": closure_failures, "GRAM_DECOMPOSITION_CLOSURE_TOL": GRAM_DECOMPOSITION_CLOSURE_TOL,
        "diagnostic_only": True, "reducer_admissible": False, "berry_or_wilson": False,
        "no_state_mixing": True, "no_qr": True, "no_lowdin": True, "no_gram_schmidt": True,
        "no_berry_or_chern": True, "no_source_anchor": True,
        "policy_contract_sha256": base.sha256_file(root / POLICY_REL),
        "policy_canonical_semantic_sha256": RP1_POLICY_CANONICAL_SHA,
        "original_rp2_execution_sha": "8121dbfba352b1a77551213771694d25c1bf3f01",
    }
    validate_worker_payload(result, row)
    return result


def _all_point_metrics(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    result = [payload["primary"]["center"], payload["control"]["center"]]
    for entry in payload["primary"]["stencils"].values():
        result.extend(entry["vertices"])
    return result


def validate_worker_payload(payload: Mapping[str, Any], row: Mapping[str, Any]) -> None:
    required = {
        "schema": WORKER_SCHEMA, "work_order_id": WORK_ORDER, "phase": PHASE,
        "worker_id": row["sample_id"], "source_sample_id": PRIMARY_SAMPLE_ID,
        "source_sample_index": int(row["source_sample_index"]), "sample_index": int(row["sample_index"]),
        "resolution": int(row["resolution"]), "authoritative_coordinate": row["authoritative_coordinate"],
        "diagnostic_only": True, "reducer_admissible": False, "berry_or_wilson": False,
        "no_state_mixing": True, "no_qr": True, "no_lowdin": True, "no_gram_schmidt": True,
    }
    for key, expected in required.items():
        if _json(payload.get(key)) != _json(expected):
            raise CampaignRuntimeError(f"RP2_C2_PAYLOAD_{key.upper()}_MISMATCH")
    if set(payload.get("primary", {}).get("stencils", {})) != set(STENCILS):
        raise CampaignRuntimeError("RP2_C2_STENCIL_COVERAGE_MISMATCH")
    if payload.get("primary", {}).get("primary_solve_count") != 9 or payload.get("control", {}).get("solve_count") != 1:
        raise CampaignRuntimeError("RP2_C2_SOLVE_COUNT_MISMATCH")
    for metric in _all_point_metrics(payload):
        if "GRAM_DECOMPOSITION_CLOSURE_MAX" not in metric or "GRAM_DECOMPOSITION_CLOSURE_TOL" not in metric:
            raise CampaignRuntimeError("RP2_C2_METRIC_RETENTION_MISSING")
        if not metric["GRAM_DECOMPOSITION_CLOSURE_PASS"] and not any(
            failure.get("MEASURED_VALUE") == metric["GRAM_DECOMPOSITION_CLOSURE_MAX"]
            and failure.get("THRESHOLD_VALUE") == GRAM_DECOMPOSITION_CLOSURE_TOL
            for failure in payload.get("closure_failures", [])
        ):
            raise CampaignRuntimeError("RP2_C2_FAIL_METRIC_NOT_RETAINED")
    for entry in payload["primary"]["stencils"].values():
        if set(entry.get("association", {})) != {"COMBINED_EH", "E_ONLY", "H_ONLY"}:
            raise CampaignRuntimeError("RP2_C2_ASSOCIATION_REPRESENTATION_COVERAGE_MISSING")
        for probe in entry["association"].values():
            if probe["precondition_pass_edges"] < 0 or probe["precondition_pass_edges"] > 4 or probe["clear_edges"] < 0 or probe["clear_edges"] > 4:
                raise CampaignRuntimeError("RP2_C2_ASSOCIATION_EDGE_COUNT_INVALID")
            for edge in probe["edges"]:
                if edge["precondition_status"] == "FAIL" and not edge.get("failure_reason"):
                    raise CampaignRuntimeError("RP2_C2_ASSOCIATION_FAILURE_REASON_MISSING")
    if payload.get("berry_or_wilson") is not False or payload.get("no_state_mixing") is not True:
        raise CampaignRuntimeError("RP2_C2_FORBIDDEN_REDUCTION_OUTPUT")


def _aggregate(rows: Sequence[Mapping[str, Any]], payloads: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    metrics = [metric for payload in payloads for metric in _all_point_metrics(payload)]
    def maximum(field: str) -> float | None:
        values = [float(metric[field]["magnitude"] if isinstance(metric[field], Mapping) else metric[field]) for metric in metrics if metric.get(field) is not None]
        return max(values) if values else None
    replay_diffs = [metric["replay"]["max_abs_difference"] for metric in metrics if metric["replay"]["max_abs_difference"] is not None]
    loops = {representation: sum(
        1 for payload in payloads for entry in payload["primary"]["stencils"].values()
        if entry["association"][representation]["ASSOCIATION_LOOP_CLOSURE"] is True
    ) for representation in ("COMBINED_EH", "E_ONLY", "H_ONLY")}
    return {
        "MAX_FULL6_EH_OFFDIAG": max(float(metric["FULL6_PROVIDER_MAX_OFFDIAG_GRAM"]) for metric in metrics),
        "MAX_PAIR_EH_OFFDIAG": maximum("PAIR_G_EH_23"),
        "MAX_PAIR_E_UNIT_OFFDIAG": maximum("PAIR_G_E_UNIT_23"),
        "MAX_PAIR_H_UNIT_OFFDIAG": maximum("PAIR_G_H_UNIT_23"),
        "association_precondition_pass_edges": {representation: sum(entry["association"][representation]["precondition_pass_edges"] for payload in payloads for entry in payload["primary"]["stencils"].values()) for representation in ("COMBINED_EH", "E_ONLY", "H_ONLY")},
        "association_clear_edges": {representation: sum(entry["association"][representation]["clear_edges"] for payload in payloads for entry in payload["primary"]["stencils"].values()) for representation in ("COMBINED_EH", "E_ONLY", "H_ONLY")},
        "loop_closure_counts_by_representation": loops,
        "E_H_ASSIGNMENT_AGREEMENT_EDGES": sum(entry["E_H_ASSIGNMENT_AGREEMENT_EDGE_COUNT"] for payload in payloads for entry in payload["primary"]["stencils"].values()),
        "MAX_ABS_FREQUENCY_REPLAY_DIFFERENCE": max(replay_diffs) if replay_diffs else None,
        "FREQUENCY_REPLAY_WITHIN_1E8": bool(replay_diffs and max(replay_diffs) <= FREQUENCY_REPLAY_TOL),
        "total_native_solves": sum(int(payload["counters"]["solver_requests"]) for payload in payloads),
    }


def run_parent(root: Path, runtime_root: Path) -> dict[str, Any]:
    assert_parent_solver_free()
    execution = load_execution_contract(root)
    rows = build_plan(root)
    execution_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    runner = root / "audit/e9f/run_e9f_c1_rp2_c2.py"
    contract_path = root / CONTRACT_REL
    plan_id = semantic_plan_fingerprint(rows, estimator_id="E9F_C1_RP2_C2_REPRESENTATION_PROBE", semantic_domain_id="RP2_PRIMARY_PLUS_K_CONTROL", spacing_id="1/72_AND_1/144")
    identity = CampaignIdentity(
        execution_sha, base.sha256_file(runner), base.sha256_file(contract_path), plan_id,
        tuple(row["sample_id"] for row in rows), expected_sample_indices=tuple(row["sample_index"] for row in rows),
        semantic_estimator_id="E9F_C1_RP2_C2_REPRESENTATION_PROBE", semantic_domain_id="RP2_PRIMARY_PLUS_K_CONTROL", semantic_spacing_id="1/72_AND_1/144",
    )
    CampaignRuntime.ARTIFACT_SCHEMA = WORKER_SCHEMA
    runtime = CampaignRuntime(Path(runtime_root), identity, runner_path=runner, contract_path=contract_path, repository_path=root, remote_name="origin", remote_ref="refs/heads/sandbox", production_mode=True)
    preflight = runtime.preflight(plan_rows=rows)
    assert_parent_solver_free()
    measurements = []
    payloads = []
    def worker(row: Mapping[str, Any]) -> Mapping[str, Any]:
        before = current_rss_kib()
        payload, measurement = run_reaped_child(worker_command(root, row), str(row["sample_id"]))
        validate_worker_payload(payload, row)
        measurement = dict(measurement)
        measurement.update({"parent_rss_before_kib": before, "parent_rss_after_kib": current_rss_kib()})
        measurements.append(measurement)
        payloads.append(payload)
        return {**payload, "process_measurement": measurement}
    run_status = runtime.run(rows, worker)
    assert_parent_solver_free()
    summary = _aggregate(rows, payloads)
    result = {
        "schema": RESULT_SCHEMA, "work_order_id": WORK_ORDER, "phase": PHASE, "stop_after": STOP_AFTER,
        "execution_identity": identity.as_dict(), "base_sha": BASE_SHA, "execution_sha": execution_sha,
        "preflight": preflight, "run_status": run_status, "worker_count": len(rows),
        "primary_sample_id": PRIMARY_SAMPLE_ID, "primary_resolutions": list(RESOLUTIONS),
        "primary_stencils": list(STENCILS), "primary_total_solves": 18,
        "control_q_public": list(CONTROL_Q_PUBLIC), "control_total_solves": 2, "total_solves": 20,
        "summary": summary, "process_measurements": measurements,
        "native_child_pids": [item["launched_pid"] for item in measurements],
        "orphan_native_child_count": sum(item["orphan_count"] for item in measurements),
        "parent_native_import_free": True, "diagnostic_only": True, "reducer_admissible": False,
        "berry_or_wilson": False, "no_state_mixing": True, "no_qr": True, "no_lowdin": True, "no_gram_schmidt": True,
        "no_berry_or_chern": True, "no_source_anchor": True, "main_promotion_authorized": False,
        "rp3_authorized": False,
        "incidents": {
            "REL_022": "CLOSED", "REL_026": "OPEN",
            "REL_027": "CORRECTIVE_IMPLEMENTED_AWAITING_LIVE_VALIDATION",
            "REL_028": "CORRECTIVE_IMPLEMENTED_AWAITING_LIVE_VALIDATION",
            "REL_029": "CORRECTIVE_IMPLEMENTED_AWAITING_LIVE_VALIDATION",
            "REL_030": "CLOSED", "REL_031": "OPEN", "REL_032": "OPEN",
        },
    }
    if result["orphan_native_child_count"] or result["worker_count"] != 2 or summary["total_native_solves"] != 20:
        raise CampaignRuntimeError("RP2_C2_PROCESS_OR_SOLVE_COVERAGE_FAIL_CLOSED")
    (Path(runtime_root) / "rp2_c2_result.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": run_status["status"], "worker_count": 2, "total_solves": 20}, sort_keys=True), flush=True)
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
        print(json.dumps({"self_check": "PASSED", "worker_count": len(rows), "primary_total_solves": 18, "control_total_solves": 2, "total_solves": 20}, sort_keys=True))
        return 0
    if args.worker:
        if args.worker_id is None or args.resolution is None or args.coordinate_json is None:
            parser.error("worker mode requires worker-id, resolution, and coordinate-json")
        row = next((item for item in build_plan(root) if item["sample_id"] == args.worker_id), None)
        if row is None:
            raise CampaignRuntimeError("RP2_C2_UNKNOWN_WORKER_ID")
        validate_worker_identity(row, worker_id=args.worker_id, resolution=args.resolution, coordinate=json.loads(args.coordinate_json))
        with contextlib.redirect_stdout(sys.stderr):
            payload = compute_worker(root, row)
        print(json.dumps(payload, sort_keys=True, allow_nan=False), flush=True)
        return 0
    runtime_root = Path(args.runtime_root) if args.runtime_root else root / "audit/e9f/rp2_c2_runtime"
    run_parent(root, runtime_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
