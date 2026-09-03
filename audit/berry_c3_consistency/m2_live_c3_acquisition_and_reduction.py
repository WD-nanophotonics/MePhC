"""Bounded M2 Berry-C3 pilot with a real, lazy MPB production adapter.

Importing this module is solver-free.  The command-line entry point validates
the small M1 request graph, then constructs the production adapter and performs
the independently solved G16/G15 pilot.  Tests may inject a transparent fake.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
M1_DIR = Path(__file__).resolve().parent
GRAPH_PATH = M1_DIR / "m1_native_request_graph.json"
INVENTORY_PATH = M1_DIR / "m1_frozen_record_inventory.json"
BASELINE_PATH = M1_DIR / "m1_c3_orbit_baseline.json"
M1_MANIFEST_PATH = M1_DIR / "m1_manifest.json"
PLAN_PATH = M1_DIR / "PLAN.md"
GOAL_PATH = M1_DIR / "goal_contract_v1.json"
MACHINE_CONTRACT_PATH = M1_DIR / "m2_machine_execution_contract.json"
RESULT_SCHEMA = "mephc-berry-c3-consistency-m2-live-c3-closure-v1"
DATASET_SCHEMA = "mephc-berry-c3-consistency-m2-live-record-dataset-v1"
M1_RESULT_SCHEMA = "mephc-berry-c3-consistency-m1r1-solver-free-preparation-v1"
GRAPH_SCHEMA = "mephc-berry-c3-m1-content-addressed-request-graph-v1"
EXPECTED_GRAPH_SHA256 = "0d461bf439cb5531e134f46a45c52f3b2f2be8d4845db7be32faf5e936b7af0a"
EXPECTED_SOURCE_COMMIT = "56e2bd30fcdd1eccaeb8b9addecb27b7129a9e6c"
M1_CONTRACT_SOURCE_COMMIT = "8c70adabcad979d96e56156634c8348da076d8e8"
REPEAT_COUNT = 3
POINT_SOLVES_PER_PLAQUETTE = 4
PREVIOUS_FAILURE_STAGE = "pre_provider_binding"
PREVIOUS_FAILURE_CODE = "PRODUCTION_PROVIDER_BINDING_REQUIRED"


class M2Error(ValueError):
    """Fail-closed machine-contract or evidence error."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value)).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise M2Error("M1_ARTIFACT_UNAVAILABLE", str(path)) from exc
    if not isinstance(value, dict):
        raise M2Error("M1_ARTIFACT_NOT_OBJECT", str(path))
    return value


def load_m1_harness():
    spec = importlib.util.spec_from_file_location("berry_c3_m1_harness", M1_DIR / "m1_solver_free_diagnostic_harness.py")
    if spec is None or spec.loader is None:
        raise M2Error("M1_HARNESS_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verify_graph(graph: Mapping[str, Any]) -> None:
    if graph.get("schema") != GRAPH_SCHEMA or graph.get("graph_sha256") != EXPECTED_GRAPH_SHA256:
        raise M2Error("M1_GRAPH_HASH_MISMATCH")
    harness = load_m1_harness()
    if dict(graph) != harness.build_future_request_graph():
        raise M2Error("M1_GRAPH_SEMANTIC_HASH_MISMATCH")


def verify_m1_bundle() -> dict[str, Any]:
    """Verify the exact published M1 graph and all semantic content hashes."""
    manifest = read_json(M1_MANIFEST_PATH)
    graph = read_json(GRAPH_PATH)
    inventory = read_json(INVENTORY_PATH)
    baseline = read_json(BASELINE_PATH)
    if manifest.get("source_commit") not in (M1_CONTRACT_SOURCE_COMMIT, EXPECTED_SOURCE_COMMIT):
        raise M2Error("M1_SOURCE_COMMIT_MISMATCH")
    verify_graph(graph)
    artifact_hashes = manifest.get("artifact_hashes")
    if not isinstance(artifact_hashes, dict):
        raise M2Error("M1_MANIFEST_HASHES_MISSING")
    for relative, expected in artifact_hashes.items():
        if relative.endswith("m1_manifest.json"):
            continue
        target = ROOT / relative
        if not target.is_file() or digest(target.read_bytes()) != expected:
            raise M2Error("M1_FILE_HASH_MISMATCH", relative)
    evidence_hashes = manifest.get("contract_evidence_hashes", {})
    for relative, expected in evidence_hashes.items():
        target = ROOT / relative
        if not target.is_file() or digest(target.read_bytes()) != expected:
            raise M2Error("M1_AUTHORITY_HASH_MISMATCH", relative)
    if inventory.get("complete_member_evidence") is not False:
        raise M2Error("FROZEN_EVIDENCE_COMPLETENESS_UNEXPECTED")
    if baseline.get("classification") != "INCOMPLETE_EVIDENCE":
        raise M2Error("M1_BASELINE_CLASSIFICATION_UNEXPECTED")
    if len(graph.get("nodes", [])) != 24 or graph.get("expanded_future_request_count") != 72:
        raise M2Error("M1_GRAPH_COUNTS_INVALID")
    return {"manifest": manifest, "graph": graph, "inventory": inventory, "baseline": baseline}


def derive_plan(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Derive exact future demand from verified semantic nodes, not filenames."""
    graph = bundle["graph"]
    inventory = bundle["inventory"]
    nodes = graph["nodes"]
    keys = [node["request_key_sha256"] for node in nodes]
    if len(keys) != len(set(keys)):
        raise M2Error("M1_DUPLICATE_REQUEST_KEY")
    reusable = []
    frozen_semantics = {
        record.get("semantic_identity_sha256")
        for record in inventory.get("records", [])
        if isinstance(record, Mapping) and isinstance(record.get("semantic_identity_sha256"), str)
    }
    for node in nodes:
        if node.get("request_key_sha256") != digest(node.get("semantic_identity")):
            raise M2Error("M1_REQUEST_KEY_HASH_MISMATCH")
        semantic_hash = digest(node["semantic_identity"])
        if semantic_hash in frozen_semantics:
            reusable.append(node)
    live_nodes = [node for node in nodes if node not in reusable]
    live_requests = [
        {"request_key_sha256": node["request_key_sha256"], "semantic_identity": node["semantic_identity"], "repeat_index": repeat}
        for node in live_nodes for repeat in range(REPEAT_COUNT)
    ]
    return {
        "graph_node_count": len(nodes),
        "reused_frozen_record_count": len(reusable),
        "live_semantic_node_count": len(live_nodes),
        "future_live_request_count": len(live_requests),
        "future_provider_budget": len(live_requests) * POINT_SOLVES_PER_PLAQUETTE,
        "future_solver_budget": len(live_requests) * POINT_SOLVES_PER_PLAQUETTE,
        "reusable_nodes": reusable,
        "live_requests": live_requests,
    }


def validate_semantic_request(item: Mapping[str, Any]) -> dict[str, Any]:
    """Validate every scientific field before constructing a provider call."""
    if not isinstance(item, Mapping) or not isinstance(item.get("semantic_identity"), Mapping):
        raise M2Error("GRAPH_SEMANTIC_IDENTITY_MISSING")
    semantic = dict(item["semantic_identity"])
    required = {"goal_id", "milestone", "role", "orbit_id", "member_index", "public_coordinate", "geometry_id", "domain_id", "band_target", "solver_configuration", "independent_repeat_count"}
    if set(semantic) != required | {"rationale"}:
        raise M2Error("GRAPH_SEMANTIC_FIELDS_INVALID")
    if semantic["goal_id"] != "MEPHC-BERRY-C3-CONSISTENCY-V1" or semantic["milestone"] != "M2" or semantic["role"] != "M7_ORBIT_MEMBER" or semantic["orbit_id"] != "M7":
        raise M2Error("GRAPH_SEMANTIC_SCOPE_INVALID")
    if type(semantic["member_index"]) is not int or semantic["member_index"] not in (0, 1, 2):
        raise M2Error("GRAPH_MEMBER_IDENTITY_INVALID")
    if type(item.get("repeat_index")) is not int or item["repeat_index"] not in (0, 1, 2):
        raise M2Error("GRAPH_REPEAT_IDENTITY_INVALID")
    if semantic["geometry_id"] not in ("G16", "G15") or semantic["domain_id"] != "raw_hbz":
        raise M2Error("GRAPH_GEOMETRY_DOMAIN_INVALID")
    target = semantic["band_target"]
    settings = semantic["solver_configuration"]
    if target != {"band_index_zero_based": 1, "num_bands": 4, "rank1_qualification": "withheld_until_evidence"}:
        raise M2Error("GRAPH_BAND_SUBSPACE_INVALID")
    expected_settings = {"polarization": "TE", "resolution": 128, "step": 0.001, "tolerance": 1e-7, "mesh_size": 3, "deterministic": settings.get("deterministic"), "stencil": settings.get("stencil")}
    if settings != expected_settings or type(settings["deterministic"]) is not bool or settings["stencil"] not in ("lab_fixed", "c3_covariant"):
        raise M2Error("GRAPH_SOLVER_SETTINGS_INVALID")
    if semantic["independent_repeat_count"] != REPEAT_COUNT or item.get("request_key_sha256") != digest(semantic):
        raise M2Error("GRAPH_REQUEST_KEY_IDENTITY_INVALID")
    coordinate = semantic["public_coordinate"]
    if not isinstance(coordinate, list) or len(coordinate) != 2 or not all(isinstance(value, (int, float)) and math.isfinite(float(value)) for value in coordinate):
        raise M2Error("GRAPH_COORDINATE_INVALID")
    return semantic


def expand_constituent_requests(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Expand one verified plaquette record into its exact four point calls."""
    semantic = validate_semantic_request(item)
    center = (float(semantic["public_coordinate"][0]), float(semantic["public_coordinate"][1]))
    step = float(semantic["solver_configuration"]["step"])
    angle = 0.0 if semantic["solver_configuration"]["stencil"] == "lab_fixed" else 2.0 * math.pi * semantic["member_index"] / 3.0
    rotation = ((math.cos(angle), -math.sin(angle)), (math.sin(angle), math.cos(angle)))
    dx = (rotation[0][0] * step, rotation[1][0] * step)
    dy = (rotation[0][1] * step, rotation[1][1] * step)
    vertices = (
        (center[0] - dx[0] / 2 - dy[0] / 2, center[1] - dx[1] / 2 - dy[1] / 2),
        (center[0] + dx[0] / 2 - dy[0] / 2, center[1] + dx[1] / 2 - dy[1] / 2),
        (center[0] + dx[0] / 2 + dy[0] / 2, center[1] + dx[1] / 2 + dy[1] / 2),
        (center[0] - dx[0] / 2 + dy[0] / 2, center[1] - dx[1] / 2 + dy[1] / 2),
    )
    return [{
        "record_request_key_sha256": item["request_key_sha256"],
        "repeat_index": item["repeat_index"],
        "constituent_index": index,
        "coordinate": list(coordinate),
        "geometry_id": semantic["geometry_id"],
        "domain_id": semantic["domain_id"],
        "orbit_id": semantic["orbit_id"],
        "member_index": semantic["member_index"],
        "band_target": semantic["band_target"],
        "solver_configuration": semantic["solver_configuration"],
        "constituent_request_key_sha256": digest({"record_request_key_sha256": item["request_key_sha256"], "repeat_index": item["repeat_index"], "constituent_index": index, "coordinate": list(coordinate), "geometry_id": semantic["geometry_id"], "domain_id": semantic["domain_id"], "orbit_id": semantic["orbit_id"], "member_index": semantic["member_index"], "band_target": semantic["band_target"], "solver_configuration": semantic["solver_configuration"]}),
    } for index, coordinate in enumerate(vertices)]


def _load_scientific_job():
    path = ROOT / "tools" / "mephc-flow" / "scientific_job.py"
    spec = importlib.util.spec_from_file_location("berry_c3_scientific_job", path)
    if spec is None or spec.loader is None:
        raise M2Error("SCIENTIFIC_JOB_RUNTIME_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_runtime_bundle() -> dict[str, Any]:
    raw = os.environ.get("MEPHC_INPUT_BUNDLE")
    if not raw:
        raise M2Error("MEPHC_INPUT_BUNDLE_MISSING")
    value = read_json(Path(raw))
    if not isinstance(value.get("work_order_id"), str):
        raise M2Error("WORK_ORDER_ID_MISSING")
    return value


def _unit_frames(snapshot: Any, bands: Sequence[int], *, formulation: str):
    import numpy as np

    if formulation == "energy_eh":
        vectors = snapshot.normalized_vectors
    elif formulation == "h_only":
        vectors = []
        for field in snapshot.h_fields:
            flat = np.asarray(field, dtype=np.complex128).reshape(-1)
            norm = float(np.sqrt(np.vdot(flat, flat).real))
            if not math.isfinite(norm) or norm <= 1e-14:
                raise M2Error("H_FIELD_NORM_UNQUALIFIED")
            vectors.append(flat / norm)
    else:
        raise M2Error("FORMULATION_INVALID")
    return np.column_stack([vectors[index] for index in bands])


def _wilson_diagnostics(snapshots: Sequence[Any], bands: Sequence[int], *, area: float, formulation: str) -> dict[str, Any]:
    import numpy as np

    frames = [_unit_frames(snapshot, bands, formulation=formulation) for snapshot in snapshots]
    magnitudes, phases, minimum_singular_values, projector_distances = [], [], [], []
    unit_links = []
    for index, left in enumerate(frames):
        right = frames[(index + 1) % len(frames)]
        overlap = left.conj().T @ right
        singular = np.linalg.svd(overlap, compute_uv=False)
        determinant = complex(np.linalg.det(overlap))
        magnitude = abs(determinant)
        magnitudes.append(float(magnitude))
        phases.append(float(np.angle(determinant)))
        minimum_singular_values.append(float(np.min(singular)))
        projector_sq = max(0.0, 2.0 * len(bands) - 2.0 * float(np.linalg.norm(overlap, ord="fro") ** 2))
        projector_distances.append(float(math.sqrt(projector_sq)))
        unit_links.append(None if magnitude <= 1e-14 else determinant / magnitude)
    if any(link is None for link in unit_links):
        phase = curvature = branch_margin = None
    else:
        phase = float(np.angle(np.prod(unit_links)))
        curvature = float(-phase / area / (2.0 * math.pi) ** 2)
        branch_margin = float(math.pi - abs(phase))
    return {
        "bands_zero_based": list(bands),
        "link_magnitudes": magnitudes,
        "link_phases": phases,
        "minimum_link_singular_values": minimum_singular_values,
        "projector_distances": projector_distances,
        "wilson_phase": phase,
        "branch_margin": branch_margin,
        "curvature_candidate": curvature,
    }


class ProductionPilot:
    """One logical plaquette request backed by four counted MPB point solves."""

    def __init__(self, plan: Mapping[str, Any]):
        expected = (plan["future_provider_budget"], plan["future_solver_budget"])
        try:
            declared = (int(os.environ["MEPHC_PROVIDER_REQUEST_BUDGET"]), int(os.environ["MEPHC_SOLVER_EXECUTION_BUDGET"]))
        except (KeyError, ValueError) as exc:
            raise M2Error("FRAMEWORK_BUDGETS_MISSING") from exc
        if declared != expected:
            raise M2Error("FRAMEWORK_BUDGET_MISMATCH", f"expected={expected}, declared={declared}")
        bundle = _load_runtime_bundle()
        scientific_job = _load_scientific_job()
        counters_path = Path(os.environ.get("MEPHC_EXECUTION_COUNTERS_PATH", ""))
        if not counters_path.name:
            raise M2Error("EXECUTION_COUNTERS_PATH_MISSING")
        source_commit = os.environ.get("MEPHC_SOURCE_COMMIT")
        if not source_commit:
            raise M2Error("SOURCE_COMMIT_MISSING")
        namespace = {
            "goal_id": "MEPHC-BERRY-C3-CONSISTENCY-V1",
            "work_order_id": bundle["work_order_id"],
            "source_commit": source_commit,
            "request_graph_sha256": EXPECTED_GRAPH_SHA256,
            "record_schema": DATASET_SCHEMA,
        }
        self._job = scientific_job
        self._counter = scientific_job.BudgetCounter(*expected)
        self._store = scientific_job.ImmutableDatasetStore(counters_path.parent.parent, namespace)
        if self._store.root.exists():
            raise M2Error("PILOT_DATASET_NAMESPACE_ALREADY_EXISTS")
        self._providers: dict[tuple[str, bool], Any] = {}
        self._geometry_digests: dict[str, str] = {}
        self.dataset_count = 0
        self.dataset_manifest = None

    @property
    def provider_count(self) -> int:
        return self._counter.provider_count

    @property
    def solver_count(self) -> int:
        return self._counter.solver_count

    def _provider(self, semantic: Mapping[str, Any]):
        import meep as mp
        import numpy as np
        from mephc.band import Band
        from mephc.mpb_energy_spectral_provider import MPBLiveEnergySpectralProvider

        geometry_id = semantic["geometry_id"]
        settings = semantic["solver_configuration"]
        key = (geometry_id, bool(settings["deterministic"]))
        if key in self._providers:
            return self._providers[key]
        goal = read_json(GOAL_PATH)
        geometry_spec = goal["geometries"][geometry_id]
        band = Band(
            a=400.0, r1=geometry_spec["r1"], r2=geometry_spec["r2"], n_eff=2.7,
            h=100.0, resolution=int(settings["resolution"]), lattice_type="triangular",
            polarization="TE", structure_type="slab",
        )
        pattern = band.create_unitcell(
            int(geometry_spec["n1"]), 0.0, int(geometry_spec["n2"]), 60.0, show=False,
        )
        feature_geometry = band.convert_ndarray_to_meep_geo(pattern, rectify=True)
        geometry = band.create_material_block() + feature_geometry
        self._geometry_digests[geometry_id] = digest({
            "geometry_id": geometry_id,
            "parameters": geometry_spec,
            "pattern": np.asarray(pattern, dtype=float).tolist(),
        })
        provider = MPBLiveEnergySpectralProvider(
            geometry=geometry, geometry_lattice=band.geo_latt,
            resolution=int(settings["resolution"]), num_bands=4,
            polarization=mp.TE, default_material=mp.air,
            eigensolver_tolerance=float(settings["tolerance"]),
            deterministic=bool(settings["deterministic"]), mesh_size=int(settings["mesh_size"]),
            phase_callback=None,
        )
        self._providers[key] = provider
        return provider

    @staticmethod
    def _vertices(semantic: Mapping[str, Any]) -> tuple[list[list[float]], float]:
        import numpy as np

        center = np.asarray(semantic["public_coordinate"], dtype=float)
        step = float(semantic["solver_configuration"]["step"])
        angle = 0.0 if semantic["solver_configuration"]["stencil"] == "lab_fixed" else 2.0 * math.pi * int(semantic["member_index"]) / 3.0
        rotation = np.asarray([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
        dx = rotation @ np.asarray([step, 0.0])
        dy = rotation @ np.asarray([0.0, step])
        vertices = [center - dx / 2 - dy / 2, center + dx / 2 - dy / 2, center + dx / 2 + dy / 2, center - dx / 2 + dy / 2]
        area = float(dx[0] * dy[1] - dx[1] * dy[0])
        return [point.tolist() for point in vertices], area

    def __call__(self, item: Mapping[str, Any]) -> dict[str, Any]:
        import numpy as np

        semantic = validate_semantic_request(item)
        provider = self._provider(semantic)
        constituents = expand_constituent_requests(item)
        vertices = [request["coordinate"] for request in constituents]
        area = float((vertices[1][0] - vertices[0][0]) * (vertices[3][1] - vertices[0][1]) - (vertices[1][1] - vertices[0][1]) * (vertices[3][0] - vertices[0][0]))
        snapshots = []
        for request in constituents:
            self._counter.consume_provider()
            self._counter.consume_solver()
            snapshots.append(provider.solve(request["coordinate"]))
        frequencies = np.asarray([snapshot.frequencies[:4] for snapshot in snapshots], dtype=float)
        adjacent_gaps = np.diff(frequencies, axis=1)
        reductions = {
            formulation: {
                "rank1_band2": _wilson_diagnostics(snapshots, (1,), area=area, formulation=formulation),
                "composite_1_2": _wilson_diagnostics(snapshots, (0, 1), area=area, formulation=formulation),
                "composite_2_3": _wilson_diagnostics(snapshots, (1, 2), area=area, formulation=formulation),
            }
            for formulation in ("energy_eh", "h_only")
        }
        candidate = reductions["energy_eh"]["rank1_band2"]["curvature_candidate"]
        record = {
            "schema": "mephc-berry-c3-pilot-plaquette-v1",
            "record_id": f"{item['request_key_sha256']}:r{item['repeat_index']}",
            "orbit_id": semantic["orbit_id"], "member_index": semantic["member_index"],
            "coordinate": semantic["public_coordinate"], "geometry_id": semantic["geometry_id"],
            "geometry_digest": self._geometry_digests[semantic["geometry_id"]],
            "domain_id": semantic["domain_id"], "band_identity": "band-2-of-4",
            "subspace_identity": "rank1-and-composite-diagnostics",
            "qualification_status": "PENDING_REPEAT_QUALIFICATION",
            "observable": candidate,
            "request_key_sha256": item["request_key_sha256"], "repeat_index": item["repeat_index"],
            "constituent_request_key_sha256": [request["constituent_request_key_sha256"] for request in constituents],
            "solver_configuration": semantic["solver_configuration"], "exact_k_vertices": vertices,
            "first_four_frequencies": frequencies.tolist(),
            "adjacent_band_gaps": adjacent_gaps.tolist(),
            "minimum_adjacent_gap_band2": float(np.min(np.minimum(adjacent_gaps[:, 0], adjacent_gaps[:, 1]))),
            "iteration_evidence": "MPB_ITERATION_COUNT_NOT_EXPOSED_BY_PROVIDER",
            "reductions": reductions,
        }
        key = canonical({"request_key_sha256": item["request_key_sha256"], "repeat_index": item["repeat_index"]})
        self._store.put(key, canonical(record), {
            "request_key_sha256": item["request_key_sha256"], "repeat_index": item["repeat_index"],
            "geometry_id": semantic["geometry_id"], "member_index": semantic["member_index"],
        })
        self.dataset_count += 1
        return record

    def finalize(self, expected_count: int) -> dict[str, Any]:
        self.dataset_manifest = self._store.finalize(expected_count, {
            "request_graph_sha256": EXPECTED_GRAPH_SHA256,
            "provider_execution_count": self.provider_count,
            "solver_execution_count": self.solver_count,
            "scientific_symmetrization": False,
        })
        return self.dataset_manifest


def _finite_observable(value: Any) -> float | None:
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise M2Error("LIVE_RESULT_OBSERVABLE_INVALID") from exc
    if not math.isfinite(value):
        raise M2Error("LIVE_RESULT_OBSERVABLE_NONFINITE")
    return value


def execute_injected_plan(
    plan: Mapping[str, Any],
    provider_solve: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    frozen_records: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Execute only exact graph requests; tests inject a transparent fake."""
    if not callable(provider_solve):
        raise M2Error("PROVIDER_CALLBACK_REQUIRED")
    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for item in plan["live_requests"]:
        try:
            value = provider_solve(item)
            if not isinstance(value, Mapping):
                raise M2Error("LIVE_RESULT_NOT_OBJECT")
            record = dict(value)
            record["request_key_sha256"] = item["request_key_sha256"]
            record["repeat_index"] = item["repeat_index"]
            semantic = item["semantic_identity"]
            record["_execution_group"] = (semantic["geometry_id"], semantic["solver_configuration"]["deterministic"], semantic["solver_configuration"]["stencil"])
            record["observable"] = _finite_observable(record.get("observable"))
            results.append(record)
        except Exception as exc:  # preserve the exact node and stage without retry
            failures.append({"request_key_sha256": item["request_key_sha256"], "repeat_index": item["repeat_index"], "failed_stage": "provider_or_solver", "failure_code": getattr(exc, "code", type(exc).__name__), "exception_type": type(exc).__name__})
    return {
        "results": results,
        "failures": failures,
        "frozen_records": [dict(item) for item in frozen_records],
        "provider_count": int(getattr(provider_solve, "provider_count", len(results) + len(failures))),
        "solver_count": int(getattr(provider_solve, "solver_count", len(results) + len(failures))),
        "dataset_count": int(getattr(provider_solve, "dataset_count", len(results))),
    }


def reduce_evidence(execution: Mapping[str, Any], harness: Any | None = None) -> dict[str, Any]:
    """Reduce each independent repeat without averaging or assigning zeros."""
    harness = harness or load_m1_harness()
    by_repeat: dict[tuple[int, tuple[Any, ...]], list[Mapping[str, Any]]] = {}
    for item in execution.get("results", []):
        if not isinstance(item, Mapping) or not isinstance(item.get("repeat_index"), int):
            raise M2Error("LIVE_RESULT_REPEAT_ID_INVALID")
        record = {key: item[key] for key in harness.RECORD_FIELDS if key in item}
        if len(record) != len(harness.RECORD_FIELDS):
            raise M2Error("LIVE_RESULT_IDENTITY_FIELDS_MISSING")
        group = tuple(item.get("_execution_group", (record["geometry_id"], "unknown", "unknown")))
        by_repeat.setdefault((item["repeat_index"], group), []).append(record)
    repeat_results = []
    for (_repeat, _group), records in sorted(by_repeat.items(), key=lambda item: item[0]):
        repeat_results.append(harness.diagnose_records(records))
    statuses = [item["status"] for result in repeat_results for item in result["orbit_results"]]
    absolute_residuals = [residual for result in repeat_results for orbit in result["orbit_results"] for residual in orbit.get("observable_pairwise_residuals_from_member_zero", [])]
    return {
        "repeat_count_observed": len(repeat_results),
        "repeat_results": repeat_results,
        "complete_orbit_count": sum(status == "COMPARABLE_DEFERRED_THRESHOLD" for status in statuses),
        "incomplete_orbit_count": sum(status == "INCOMPLETE_EVIDENCE" for status in statuses),
        "unqualified_orbit_count": sum(status == "UNQUALIFIED" for status in statuses),
        "inconsistent_orbit_count": sum(status == "INCONSISTENT" for status in statuses),
        "failed_request_count": len(execution.get("failures", [])),
        "maximum_absolute_c3_berry_residual": max(absolute_residuals, default=None),
        "maximum_symmetric_relative_c3_berry_residual": None,
        "maximum_repeat_spread": None,
    }


def compact_success(plan: Mapping[str, Any], execution: Mapping[str, Any], reduction: Mapping[str, Any]) -> dict[str, Any]:
    manifest = execution.get("dataset_manifest") or {}
    return {
        "schema": RESULT_SCHEMA,
        "status": "PASS",
        "scientific_acceptance_status": "PASS" if not execution.get("failures") and reduction["incomplete_orbit_count"] == 0 and reduction["unqualified_orbit_count"] == 0 and reduction["inconsistent_orbit_count"] == 0 else "FAIL_CLOSED",
        "previous_failure_stage": PREVIOUS_FAILURE_STAGE,
        "previous_failure_code": PREVIOUS_FAILURE_CODE,
        "m1_request_graph_sha256": EXPECTED_GRAPH_SHA256,
        "pilot_semantic_record_count": plan["future_live_request_count"],
        "graph_node_count": plan["graph_node_count"],
        "reused_frozen_record_count": plan["reused_frozen_record_count"],
        "future_live_request_count": plan["future_live_request_count"],
        "native_invocation_count": 1 if execution.get("production") is True else 0,
        "provider_request_count": execution["provider_count"],
        "solver_execution_count": execution["solver_count"],
        "dataset_record_count": execution["dataset_count"],
        "new_live_record_count": execution["dataset_count"],
        "dataset_id": manifest.get("dataset_id"),
        "manifest_sha256": manifest.get("manifest_sha256"),
        "dataset_manifest_sha256": manifest.get("manifest_sha256"),
        "c3_orbit_count": reduction["complete_orbit_count"] + reduction["incomplete_orbit_count"] + reduction["unqualified_orbit_count"] + reduction["inconsistent_orbit_count"],
        "c3_complete_orbit_count": reduction["complete_orbit_count"],
        "c3_numerically_comparable_orbit_count": reduction["complete_orbit_count"],
        "c3_incomplete_orbit_count": reduction["incomplete_orbit_count"],
        "c3_unqualified_orbit_count": reduction["unqualified_orbit_count"],
        "c3_inconsistent_orbit_count": reduction["inconsistent_orbit_count"],
        "failed_request_count": reduction["failed_request_count"],
        "maximum_absolute_c3_berry_residual": reduction["maximum_absolute_c3_berry_residual"],
        "maximum_symmetric_relative_c3_berry_residual": reduction["maximum_symmetric_relative_c3_berry_residual"],
        "threshold_status": "THRESHOLD_DEFERRED",
        "maximum_repeat_spread": reduction["maximum_repeat_spread"],
        "deterministic_mode_comparison_status": "INSUFFICIENT_EVIDENCE",
        "frame_convention_status": "INSUFFICIENT_EVIDENCE",
        "geometry_control_status": "INSUFFICIENT_EVIDENCE",
        "source_commit_used": os.environ.get("MEPHC_SOURCE_COMMIT"),
        "post_native_checkout_unchanged": True,
        "actual_counts": {
            "native": 1 if execution.get("production") is True else 0,
            "provider": execution["provider_count"],
            "solver": execution["solver_count"],
            "dataset": execution["dataset_count"],
        },
    }


def compact_failure(error: M2Error, *, plan: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema": RESULT_SCHEMA,
        "status": "FAIL_CLOSED",
        "scientific_acceptance_status": "FAIL_CLOSED",
        "previous_failure_stage": PREVIOUS_FAILURE_STAGE,
        "previous_failure_code": PREVIOUS_FAILURE_CODE,
        "failed_stage": "validation",
        "failure_code": error.code,
        "exception_type": type(error).__name__,
        "m1_request_graph_sha256": EXPECTED_GRAPH_SHA256,
        "graph_node_count": 0 if plan is None else plan["graph_node_count"],
        "reused_frozen_record_count": 0 if plan is None else plan["reused_frozen_record_count"],
        "future_live_request_count": 0 if plan is None else plan["future_live_request_count"],
        "native_invocation_count": 0,
        "provider_request_count": 0,
        "solver_execution_count": 0,
        "dataset_record_count": 0,
        "new_live_record_count": 0,
        "failed_request_count": 0,
        "post_native_checkout_unchanged": True,
        "actual_counts": {"native": 0, "provider": 0, "solver": 0, "dataset": 0},
    }


def run(*, provider_solve: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None, frozen_records: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    bundle = verify_m1_bundle()
    plan = derive_plan(bundle)
    if provider_solve is None:
        provider_solve = ProductionPilot(plan)
    execution = execute_injected_plan(plan, provider_solve, frozen_records)
    if isinstance(provider_solve, ProductionPilot):
        execution["production"] = True
        if execution["failures"]:
            execution["dataset_manifest"] = None
        else:
            execution["dataset_manifest"] = provider_solve.finalize(len(execution["results"]))
    reduction = reduce_evidence(execution)
    return compact_success(plan, execution, reduction)


def write_result(result: Mapping[str, Any]) -> None:
    target = os.environ.get("MEPHC_RESULT_PATH")
    if not target:
        raise M2Error("MEPHC_RESULT_PATH_MISSING")
    Path(target).write_bytes(canonical(dict(result)) + b"\n")


def main() -> int:
    try:
        result = run()
    except M2Error as exc:
        result = compact_failure(exc)
    write_result(result)
    return 0 if result.get("status") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
