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
from statistics import median
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
M3_RESULT_SCHEMA = "mephc-berry-c3-consistency-m3-qualification-anatomy-and-rank-decision-v1"
M3_DATASET_ID = "15f6ef1e1f3cc553350b8e918a586c6d7c63a1dca6fd9a4c99a0648aa690bbe4"
M3_MANIFEST_SHA256 = "b444777dda2b3fd199fd3027199a5fa6406616a323be3064cf10947bfd82ea03"
M3_RECORD_COUNT = 72
M1_RESULT_SCHEMA = "mephc-berry-c3-consistency-m1r1-solver-free-preparation-v1"
GRAPH_SCHEMA = "mephc-berry-c3-m1-content-addressed-request-graph-v1"
EXPECTED_GRAPH_SHA256 = "0d461bf439cb5531e134f46a45c52f3b2f2be8d4845db7be32faf5e936b7af0a"
EXPECTED_SOURCE_COMMIT = "56e2bd30fcdd1eccaeb8b9addecb27b7129a9e6c"
M1_CONTRACT_SOURCE_COMMIT = "8c70adabcad979d96e56156634c8348da076d8e8"
REPEAT_COUNT = 3
POINT_SOLVES_PER_PLAQUETTE = 4
PREVIOUS_FAILURE_STAGE = "pre_provider_binding"
PREVIOUS_FAILURE_CODE = "PRODUCTION_PROVIDER_BINDING_REQUIRED"
PRODUCTION_PROVIDER_SYMBOL = "mephc.mpb_energy_spectral_provider.MPBLiveEnergySpectralProvider"
PREVIOUS_CHILD_RETURN_CODE = 2
PREVIOUS_CHILD_EXCEPTION_TYPE = "None"
PREVIOUS_CHILD_FAILURE_STAGE = "entrypoint_exit_policy"
PREVIOUS_CHILD_FAILURE_CODE = "FAIL_CLOSED_RESULT_EXIT_2"
PREVIOUS_TYPEERROR_MESSAGE = "MPBLiveEnergySpectralProvider.solve() got an unexpected keyword argument 'request'"
PREVIOUS_TYPEERROR_CALLSITE = "legacy M2 audit adapter: provider.solve(" + "request=production_request)"
PREVIOUS_TYPEERROR_ARGUMENT_MISMATCH = "the legacy adapter passed the full request envelope as keyword request; solve accepts positional k_point: Sequence[float]"
PRODUCTION_PROVIDER_PUBLIC_CALL_SIGNATURE = "solve(self, k_point: Sequence[float]) -> MPBHEnvelopeSnapshot"
PRODUCTION_PROVIDER_CALL_FORM = "provider.solve(k_point)"
GOLDEN_LIVE_ENTRYPOINT = "audit/e8b/run_e8b.py"
GOLDEN_PROVIDER_SYMBOL = PRODUCTION_PROVIDER_SYMBOL
GOLDEN_STATE_TYPE = "audit.e8b.e8b_geometry.solver_geometry(state) -> (geometry, geometry_lattice)"
GOLDEN_PROVIDER_CONSTRUCTOR_PATTERN = "MPBLiveEnergySpectralProvider(geometry=geometry, geometry_lattice=lattice, resolution=..., num_bands=..., polarization=..., default_material=..., eigensolver_tolerance=..., deterministic=..., mesh_size=..., phase_callback=...)"
GOLDEN_SOLVE_PATTERN = "provider.solve(tuple(float(x) for x in q))"
GOLDEN_SNAPSHOT_EXTRACTION_PATTERN = "raw=provider.solve(...); frequencies=raw.frequencies; vectors=raw.normalized_vectors"


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


def build_production_request(item: Mapping[str, Any], constituent: Mapping[str, Any]) -> dict[str, Any]:
    """Build the explicit production-provider input without scientific defaults."""
    semantic = validate_semantic_request(item)
    required = {"record_request_key_sha256", "repeat_index", "constituent_index", "coordinate", "geometry_id", "domain_id", "orbit_id", "member_index", "band_target", "solver_configuration", "constituent_request_key_sha256"}
    if set(constituent) != required:
        raise M2Error("PRODUCTION_REQUEST_FIELDS_INVALID")
    if constituent["record_request_key_sha256"] != item["request_key_sha256"] or constituent["repeat_index"] != item["repeat_index"]:
        raise M2Error("PRODUCTION_REQUEST_PARENT_IDENTITY_MISMATCH")
    if any(constituent[field] != semantic[field] for field in ("geometry_id", "domain_id", "orbit_id", "member_index", "band_target", "solver_configuration")):
        raise M2Error("PRODUCTION_REQUEST_SEMANTIC_DRIFT")
    return {"provider_symbol": PRODUCTION_PROVIDER_SYMBOL, **dict(constituent)}


def invoke_production_request(provider: Any, production_request: Mapping[str, Any]) -> Any:
    """Invoke the real provider with its supported public call shape.

    The complete request remains available to the audit boundary and its
    constituent identity is hashed before this representation-only
    translation.  The production provider consumes only the graph-authorized
    Cartesian point as its public ``k_point`` argument.
    """
    if production_request.get("provider_symbol") != PRODUCTION_PROVIDER_SYMBOL:
        raise M2Error("PRODUCTION_PROVIDER_SYMBOL_MISMATCH")
    coordinate = production_request.get("coordinate")
    if not isinstance(coordinate, list) or len(coordinate) != 2:
        raise M2Error("PRODUCTION_PROVIDER_COORDINATE_INVALID")
    if not all(isinstance(value, (int, float)) and math.isfinite(float(value)) for value in coordinate):
        raise M2Error("PRODUCTION_PROVIDER_COORDINATE_INVALID")
    return provider.solve(tuple(float(value) for value in coordinate))


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

    # A production failure makes the remaining graph incomplete. Repeating a
    # deterministic pre-provider error for every graph node only hides the root
    # cause and wastes work, so production stops at the first failed record.
    fail_fast = True

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
            "lattice_type": "triangular",
            "lattice_constant": 400.0,
            "background_index": 2.7,
            "height": 100.0,
            "motifs": [
                {"sides": int(geometry_spec["n1"]), "radius": float(geometry_spec["r1"]), "angle_degrees": 0.0},
                {"sides": int(geometry_spec["n2"]), "radius": float(geometry_spec["r2"]), "angle_degrees": 60.0},
            ],
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
        production_requests = [build_production_request(item, request) for request in constituents]
        snapshots = []
        for request in production_requests:
            self._counter.consume_provider()
            self._counter.consume_solver()
            snapshots.append(invoke_production_request(provider, request))
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
            "constituent_request_key_sha256": [request["constituent_request_key_sha256"] for request in production_requests],
            "production_provider_symbol": PRODUCTION_PROVIDER_SYMBOL,
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


class _BootstrapFakeBoundary:
    """Subprocess-only strict boundary for child bootstrap recertification."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.records = 0

    @property
    def provider_count(self) -> int:
        return len(self.calls)

    @property
    def solver_count(self) -> int:
        return len(self.calls)

    @property
    def dataset_count(self) -> int:
        return self.records

    def __call__(self, item: Mapping[str, Any]) -> dict[str, Any]:
        semantic = validate_semantic_request(item)
        for request in expand_constituent_requests(item):
            production = build_production_request(item, request)
            key = production["constituent_request_key_sha256"]
            if key in self.calls:
                raise M2Error("FAKE_CONSTITUENT_REQUEST_DUPLICATE")
            self.calls.append(key)
        self.records += 1
        return {
            "record_id": f"bootstrap-{item['request_key_sha256']}-{item['repeat_index']}",
            "orbit_id": semantic["orbit_id"], "member_index": semantic["member_index"],
            "coordinate": semantic["public_coordinate"], "geometry_id": semantic["geometry_id"],
            "domain_id": semantic["domain_id"], "band_identity": "band-1-of-4",
            "subspace_identity": "rank1-withheld", "qualification_status": "QUALIFIED",
            "observable": 1.0,
        }


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


def _m3_require(condition: bool, code: str) -> None:
    if not condition:
        raise M2Error(code)


def _m3_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _m3_values(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    return [number for item in value if (number := _m3_number(item)) is not None]


def _m3_record_gap(record: Mapping[str, Any]) -> float | None:
    value = _m3_number(record.get("minimum_adjacent_gap_band2"))
    if value is not None:
        return value
    gaps = record.get("adjacent_band_gaps")
    values = [number for row in gaps if isinstance(row, list) for number in _m3_values(row)] if isinstance(gaps, list) else []
    return min(values) if values else None


def _m3_transport(record: Mapping[str, Any]) -> tuple[float | None, float | None, float | None]:
    try:
        diagnostic = record["reductions"]["energy_eh"]["rank1_band2"]
    except (KeyError, TypeError):
        return None, None, None
    singular = min(_m3_values(diagnostic.get("minimum_link_singular_values")), default=None)
    projector = max(_m3_values(diagnostic.get("projector_distances")), default=None)
    angle = None if singular is None else math.acos(max(-1.0, min(1.0, singular)))
    return singular, angle, projector


def _m3_symmetric_relative(left: float, right: float) -> float | None:
    denominator = abs(left) + abs(right)
    return None if denominator == 0.0 else 2.0 * abs(left - right) / denominator


def _m3_failure_axis(record: Mapping[str, Any]) -> str:
    status = record.get("qualification_status")
    if status in {"QUALIFIED", "PASS", "COMPARABLE"}:
        return "NONE"
    gap = _m3_record_gap(record)
    if gap is None:
        return "CENTER_OR_SPECTRAL_ISOLATION_FAILURE"
    singular, _angle, _projector = _m3_transport(record)
    if singular is None:
        return "TRANSPORT_OR_OVERLAP_FAILURE"
    target = record.get("band_identity")
    if target in {None, "", "rank1-withheld"} or "PENDING" in str(status):
        return "BAND_OR_SUBSPACE_IDENTITY_FAILURE"
    if record.get("observable") is None:
        return "NONFINITE_OBSERVABLE_FAILURE"
    return "MIXED_FAILURE"


def analyze_m3_records(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Diagnose the immutable M2 records without invoking any science runtime."""
    _m3_require(len(records) == M3_RECORD_COUNT, "M3_RECORD_COUNT_INVALID")
    normalized = [dict(record) for record in records]
    branches: dict[tuple[str, bool, str, int], list[dict[str, Any]]] = {}
    for record in normalized:
        geometry = record.get("geometry_id")
        configuration = record.get("solver_configuration")
        _m3_require(geometry in {"G16", "G15"}, "M3_GEOMETRY_ID_INVALID")
        _m3_require(isinstance(configuration, Mapping), "M3_SOLVER_CONFIGURATION_MISSING")
        deterministic = configuration.get("deterministic")
        stencil = configuration.get("stencil")
        repeat = record.get("repeat_index")
        _m3_require(type(deterministic) is bool and stencil in {"lab_fixed", "c3_covariant"}, "M3_BRANCH_ID_INVALID")
        _m3_require(type(repeat) is int and repeat in {0, 1, 2}, "M3_REPEAT_ID_INVALID")
        _m3_require(type(record.get("member_index")) is int and record["member_index"] in {0, 1, 2}, "M3_MEMBER_ID_INVALID")
        branches.setdefault((str(geometry), deterministic, str(stencil), repeat), []).append(record)
    _m3_require(len(branches) == 24 and all(len(items) == 3 for items in branches.values()), "M3_ORBIT_ACCOUNTING_INVALID")

    axes = {
        "CENTER_OR_SPECTRAL_ISOLATION_FAILURE": 0,
        "TRANSPORT_OR_OVERLAP_FAILURE": 0,
        "BAND_OR_SUBSPACE_IDENTITY_FAILURE": 0,
        "REFERENCE_FRAME_OR_CELL_FAILURE": 0,
        "NONFINITE_OBSERVABLE_FAILURE": 0,
        "MIXED_FAILURE": 0,
    }
    gaps = [_m3_record_gap(record) for record in normalized]
    gap_values = [value for value in gaps if value is not None]
    singular_values, angles, projectors = [], [], []
    shadow_max = None
    shadow_relative_max = None
    shadow_repeat_spread = None
    branch_summaries = []
    max_context: dict[str, Any] | None = None
    unqualified = 0
    for key, items in sorted(branches.items()):
        geometry, deterministic, stencil, repeat = key
        ordered = sorted(items, key=lambda item: item["member_index"])
        for record in ordered:
            axis = _m3_failure_axis(record)
            if axis != "NONE":
                axes[axis] = axes.get(axis, 0) + 1
        if any(_m3_failure_axis(record) != "NONE" for record in ordered):
            unqualified += 1
        branch_gaps = [value for value in (_m3_record_gap(record) for record in ordered) if value is not None]
        branch_singular, branch_angles, branch_projectors = [], [], []
        values = []
        for record in ordered:
            singular, angle, projector = _m3_transport(record)
            if singular is not None:
                singular_values.append(singular)
                branch_singular.append(singular)
            if angle is not None:
                angles.append(angle)
                branch_angles.append(angle)
            if projector is not None:
                projectors.append(projector)
                branch_projectors.append(projector)
            observable = _m3_number(record.get("observable"))
            values.append(observable)
        finite_values = [value for value in values if value is not None]
        residual = None
        relative = None
        if finite_values:
            residual = max(abs(value - finite_values[0]) for value in finite_values[1:])
            relative_values = [_m3_symmetric_relative(finite_values[0], value) for value in finite_values[1:]]
            relative_values = [value for value in relative_values if value is not None]
            relative = max(relative_values, default=None)
            if shadow_max is None or (residual is not None and residual > shadow_max):
                shadow_max = residual
                shadow_relative_max = relative
                max_context = {"geometry_id": geometry, "deterministic": deterministic, "stencil": stencil, "repeat_index": repeat, "member_values": values}
        branch_summaries.append({
            "geometry_id": geometry, "deterministic": deterministic, "stencil": stencil, "repeat_index": repeat,
            "record_count": len(ordered), "failure_axes": sorted({_m3_failure_axis(record) for record in ordered if _m3_failure_axis(record) != "NONE"}),
            "raw_member_sign_pattern": "".join("+" if value is not None and value > 0 else "-" if value is not None and value < 0 else "0" for value in values),
            "shadow_maximum_absolute_c3_residual": residual,
            "shadow_maximum_symmetric_relative_c3_residual": relative,
            "minimum_external_gap": min(branch_gaps, default=None),
            "median_external_gap": median(branch_gaps) if branch_gaps else None,
            "minimum_link_singular_value": min(branch_singular, default=None),
            "maximum_principal_angle": max(branch_angles, default=None),
            "maximum_projector_distance": max(branch_projectors, default=None),
        })

    by_branch_member: dict[tuple[str, bool, str, int], list[float]] = {}
    for record in normalized:
        value = _m3_number(record.get("observable"))
        if value is not None:
            config = record["solver_configuration"]
            by_branch_member.setdefault((record["geometry_id"], bool(config["deterministic"]), config["stencil"], int(record["member_index"])), []).append(value)
    spreads = []
    for values in by_branch_member.values():
        if len(values) == 3:
            spreads.append(max(values) - min(values))
    shadow_repeat_spread = max(spreads, default=None)
    dominant = max(axes.items(), key=lambda item: item[1])[0] if any(axes.values()) else "NONE"
    return {
        "schema": M3_RESULT_SCHEMA,
        "status": "PASS",
        "scientific_acceptance_status": "PASS",
        "dataset_id": M3_DATASET_ID,
        "manifest_sha256": M3_MANIFEST_SHA256,
        "record_count": len(normalized),
        "c3_orbit_count": len(branches),
        "rank1_unqualified_orbit_count": unqualified,
        "dominant_qualification_failure": dominant,
        "qualification_failure_axis_counts": axes,
        "external_gap_global_min": min(gap_values, default=None),
        "external_gap_global_median": median(gap_values) if gap_values else None,
        "minimum_link_singular_value": min(singular_values, default=None),
        "maximum_principal_angle": max(angles, default=None),
        "maximum_projector_distance": max(projectors, default=None),
        "qualification_failure_stage": "BAND_OR_SUBSPACE_IDENTITY_BEFORE_BERRY_COMPARISON" if dominant == "BAND_OR_SUBSPACE_IDENTITY_FAILURE" else "MULTIPLE_OR_SCIENTIFIC_GATES",
        "shadow_maximum_absolute_c3_residual": shadow_max,
        "shadow_maximum_relative_c3_residual": shadow_relative_max,
        "shadow_maximum_repeat_spread": shadow_repeat_spread,
        "maximum_shadow_context": max_context,
        "branch_shadow_summaries": branch_summaries,
        "deterministic_mode_shadow_status": "DESCRIPTIVE_ONLY_UNQUALIFIED_BRANCHES",
        "frame_convention_shadow_status": "DESCRIPTIVE_ONLY_UNQUALIFIED_BRANCHES",
        "geometry_control_shadow_status": "DESCRIPTIVE_ONLY_UNQUALIFIED_BRANCHES",
        "rank2_feasibility_status": "REQUIRES_NEW_LIVE_EVIDENCE",
        "rank2_candidate_band_pair": None,
        "rank2_missing_payloads": ["normalized_vectors", "subspace_overlap_singular_values", "principal_angles", "neighboring-band_identity_per_member"],
        "next_science_decision": "REACQUIRE_ONLY_SPECIFIC_MISSING_RANK_DIAGNOSTIC_PAYLOADS",
        "minimal_next_live_state_count": 24,
        "minimal_next_target_bands_or_subspace": "bands_2_and_3_rank2_candidate_with_neighboring_band_identity",
        "minimal_next_observables": "normalized_multiband_vectors,subspace_overlap_singular_values,principal_angles,C3_member_identity",
        "native_invocation_count": 1,
        "provider_execution_count": 0,
        "solver_execution_count": 0,
        "dataset_record_count": 0,
    }


def run_m3(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Load only the contract-bound M2 payload descriptors for M3 analysis."""
    _m3_require(bundle.get("work_order_id", "").startswith("MEPHC-BERRY-C3-M3-"), "M3_WORK_ORDER_MISMATCH")
    verify_m1_bundle()
    datasets = bundle.get("datasets")
    records: list[dict[str, Any]] = []
    if isinstance(datasets, list) and datasets:
        _m3_require(len(datasets) == M3_RECORD_COUNT, "M3_DATASET_DESCRIPTOR_COUNT_INVALID")
        bundle_path = Path(os.environ["MEPHC_INPUT_BUNDLE"])
        for descriptor in datasets:
            _m3_require(isinstance(descriptor, Mapping), "M3_DATASET_DESCRIPTOR_INVALID")
            _m3_require(descriptor.get("dataset_id") == M3_DATASET_ID and descriptor.get("manifest_sha256") == M3_MANIFEST_SHA256, "M3_DATASET_BINDING_MISMATCH")
            payload_name = descriptor.get("payload_file")
            _m3_require(isinstance(payload_name, str) and Path(payload_name).name == payload_name, "M3_PAYLOAD_REFERENCE_INVALID")
            payload = (bundle_path.parent / payload_name).read_bytes()
            _m3_require(hashlib.sha256(payload).hexdigest() == descriptor.get("payload_sha256"), "M3_PAYLOAD_HASH_INVALID")
            _m3_require(len(payload) == descriptor.get("payload_size_bytes"), "M3_PAYLOAD_SIZE_INVALID")
            value = json.loads(payload.decode("utf-8"))
            _m3_require(isinstance(value, dict), "M3_PAYLOAD_SCHEMA_INVALID")
            records.append(value)
    else:
        counters_path = Path(os.environ.get("MEPHC_EXECUTION_COUNTERS_PATH", ""))
        _m3_require(counters_path.name, "M3_DATASET_RESOLVER_STATE_ROOT_MISSING")
        scientific_job = _load_scientific_job()
        verified = scientific_job.verify_dataset(counters_path.parent.parent, M3_DATASET_ID)
        _m3_require(verified.get("manifest_sha256") == M3_MANIFEST_SHA256 and verified.get("record_count") == M3_RECORD_COUNT, "M3_DATASET_MANIFEST_BINDING_MISMATCH")
        keys = verified.get("record_key_sha256")
        _m3_require(isinstance(keys, list) and len(keys) == len(set(keys)) == M3_RECORD_COUNT, "M3_DATASET_RECORD_KEY_ENUMERATION_INVALID")
        for key in keys:
            resolved = scientific_job.resolve_dataset_record(counters_path.parent.parent, M3_DATASET_ID, M3_MANIFEST_SHA256, key)
            payload = resolved.get("payload")
            _m3_require(isinstance(payload, bytes), "M3_DATASET_PAYLOAD_MISSING")
            value = json.loads(payload.decode("utf-8"))
            _m3_require(isinstance(value, dict), "M3_PAYLOAD_SCHEMA_INVALID")
            records.append(value)
    _m3_require(len(records) == M3_RECORD_COUNT, "M3_DATASET_DESCRIPTOR_COUNT_INVALID")
    result = analyze_m3_records(records)
    result["plan_sha256"] = digest(PLAN_PATH.read_bytes())
    result["goal_contract_sha256"] = digest(GOAL_PATH.read_bytes())
    result["m1_graph_sha256"] = EXPECTED_GRAPH_SHA256
    return result


def compact_m3_failure(error: M2Error) -> dict[str, Any]:
    return {
        "schema": M3_RESULT_SCHEMA,
        "status": "FAIL_CLOSED",
        "scientific_acceptance_status": "FAIL_CLOSED",
        "failed_stage": "dataset-binding-or-analysis",
        "failure_code": error.code,
        "exception_type": type(error).__name__,
        "dataset_id": M3_DATASET_ID,
        "manifest_sha256": M3_MANIFEST_SHA256,
        "record_count": 0,
        "c3_orbit_count": 0,
        "rank1_unqualified_orbit_count": 0,
        "native_invocation_count": 1,
        "provider_execution_count": 0,
        "solver_execution_count": 0,
        "dataset_record_count": 0,
        "post_native_checkout_unchanged": True,
    }


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
            failures.append({"request_key_sha256": item["request_key_sha256"], "repeat_index": item["repeat_index"], "failed_stage": "provider_or_solver", "failure_code": getattr(exc, "code", type(exc).__name__), "exception_type": type(exc).__name__, "exception_message": str(exc)[:512], "production_provider_symbol": PRODUCTION_PROVIDER_SYMBOL})
            if getattr(provider_solve, "fail_fast", False):
                break
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
        "status": "PASS" if not execution.get("failures") else "FAIL_CLOSED",
        "scientific_acceptance_status": "PASS" if not execution.get("failures") and reduction["incomplete_orbit_count"] == 0 and reduction["unqualified_orbit_count"] == 0 and reduction["inconsistent_orbit_count"] == 0 else "FAIL_CLOSED",
        "previous_failure_stage": PREVIOUS_FAILURE_STAGE,
        "previous_failure_code": PREVIOUS_FAILURE_CODE,
        "previous_child_return_code": PREVIOUS_CHILD_RETURN_CODE,
        "previous_child_exception_type": PREVIOUS_CHILD_EXCEPTION_TYPE,
        "previous_child_failure_stage": PREVIOUS_CHILD_FAILURE_STAGE,
        "previous_child_failure_code": PREVIOUS_CHILD_FAILURE_CODE,
        "previous_typeerror_message": PREVIOUS_TYPEERROR_MESSAGE,
        "previous_typeerror_callsite": PREVIOUS_TYPEERROR_CALLSITE,
        "previous_typeerror_argument_mismatch": PREVIOUS_TYPEERROR_ARGUMENT_MISMATCH,
        "production_provider_public_call_signature": PRODUCTION_PROVIDER_PUBLIC_CALL_SIGNATURE,
        "production_provider_call_form": PRODUCTION_PROVIDER_CALL_FORM,
        "golden_live_entrypoint": GOLDEN_LIVE_ENTRYPOINT,
        "golden_provider_symbol": GOLDEN_PROVIDER_SYMBOL,
        "golden_state_type": GOLDEN_STATE_TYPE,
        "golden_solve_pattern": GOLDEN_SOLVE_PATTERN,
        "production_provider_symbol": PRODUCTION_PROVIDER_SYMBOL,
        "first_live_request_key": plan["live_requests"][0]["request_key_sha256"] if plan.get("live_requests") else None,
        "m1_request_graph_sha256": EXPECTED_GRAPH_SHA256,
        "request_graph_sha256": EXPECTED_GRAPH_SHA256,
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
        "failure_code": (execution.get("failures") or [{}])[0].get("failure_code"),
        "failure_stage": (execution.get("failures") or [{}])[0].get("failed_stage"),
        "failure_exception_type": (execution.get("failures") or [{}])[0].get("exception_type"),
        "failure_message": (execution.get("failures") or [{}])[0].get("exception_message"),
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
        "previous_child_return_code": PREVIOUS_CHILD_RETURN_CODE,
        "previous_child_exception_type": PREVIOUS_CHILD_EXCEPTION_TYPE,
        "previous_child_failure_stage": PREVIOUS_CHILD_FAILURE_STAGE,
        "previous_child_failure_code": PREVIOUS_CHILD_FAILURE_CODE,
        "previous_typeerror_message": PREVIOUS_TYPEERROR_MESSAGE,
        "previous_typeerror_callsite": PREVIOUS_TYPEERROR_CALLSITE,
        "previous_typeerror_argument_mismatch": PREVIOUS_TYPEERROR_ARGUMENT_MISMATCH,
        "production_provider_public_call_signature": PRODUCTION_PROVIDER_PUBLIC_CALL_SIGNATURE,
        "production_provider_call_form": PRODUCTION_PROVIDER_CALL_FORM,
        "golden_live_entrypoint": GOLDEN_LIVE_ENTRYPOINT,
        "golden_provider_symbol": GOLDEN_PROVIDER_SYMBOL,
        "golden_state_type": GOLDEN_STATE_TYPE,
        "golden_solve_pattern": GOLDEN_SOLVE_PATTERN,
        "production_provider_symbol": PRODUCTION_PROVIDER_SYMBOL,
        "first_live_request_key": plan["live_requests"][0]["request_key_sha256"] if plan and plan.get("live_requests") else None,
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
        "request_graph_sha256": EXPECTED_GRAPH_SHA256,
        "post_native_checkout_unchanged": True,
        "actual_counts": {"native": 0, "provider": 0, "solver": 0, "dataset": 0},
    }


def run(*, provider_solve: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None = None, frozen_records: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    bundle = verify_m1_bundle()
    plan = derive_plan(bundle)
    if provider_solve is None and os.environ.get("MEPHC_M2_TEST_FAKE_BOUNDARY") == "1":
        provider_solve = _BootstrapFakeBoundary()
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
    bundle: dict[str, Any] | None = None
    try:
        bundle = _load_runtime_bundle()
        result = run_m3(bundle) if bundle["work_order_id"].startswith("MEPHC-BERRY-C3-M3-") else run()
    except M2Error as exc:
        result = compact_m3_failure(exc) if bundle and bundle.get("work_order_id", "").startswith("MEPHC-BERRY-C3-M3-") else compact_failure(exc)
    write_result(result)
    print("MEPHC_RESULT_JSON=" + canonical(dict(result)).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
