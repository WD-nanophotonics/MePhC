from __future__ import annotations

import hashlib
import json
import sys
import types
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m41r3_recover36_finish_convergence.py"
SPEC = __import__("importlib.util").util.spec_from_file_location("m41r3", SOURCE)
assert SPEC and SPEC.loader
m41r3 = __import__("importlib.util").util.module_from_spec(SPEC)
SPEC.loader.exec_module(m41r3)


def _record(module, member: str, member_index: int, repeat: int, vertex: int, configuration: str, schema: str, center: list[float]) -> dict:
    vertices, _ = module._plaquette_vertices(center, member_index)
    return {
        "schema": schema,
        "configuration_id": configuration,
        "c3_member_identity": member,
        "member_index": member_index,
        "repeat_index": repeat,
        "vertex_index": vertex,
        "geometry_id": "G15",
        "geometry_role": "AREA_MATCHED_G15",
        "stencil": "C3_COVARIANT",
        "deterministic": True,
        "resolution": 128,
        "tolerance": 1e-9,
        "mesh_size": 3,
        "center": center,
        "coordinate": vertices[vertex],
        "adjacent_gaps": {"lower_gap": 1.0, "internal_split": 1.0, "upper_gap": 1.0},
        "raw_eigenvector": {"fake": True},
    }


def test_resolution_helpers_cover_all_declared_shapes_and_counts():
    raw = np.ones((4, 4, 2), dtype=np.complex128)
    canonical, diagnostics = m41r3._normalize_raw(raw, 2)
    assert canonical.shape == (4, 4, 2)
    assert diagnostics["four_band_gram_normalization_residual"] < 1e-12
    assert m41r3.MODE_COUNT_BY_RESOLUTION == {64: 4096, 96: 9216, 128: 16384}
    source = SOURCE.read_text(encoding="utf-8")
    assert "fft_label(index, shape=shape)" in source
    assert "QR" in source or "np.linalg.qr" in source


def test_graph_is_exactly_36_and_excludes_parent_configuration():
    centers = {member: [float(i + 1), float(i) + 0.25] for i, member in enumerate(m41r3.MEMBERS)}
    graph = m41r3._new_graph({"configuration_id": "R64_T1E9_M3", "resolution": 64, "tolerance": 1e-9, "mesh_size": 3}, centers, "a" * 40)
    assert len(graph) == 36
    assert len({row["request_key_sha256"] for row in graph}) == 36
    assert all(row["configuration_id"] != "R128_T1E9_M3" for row in graph)


def test_rank2_analysis_and_complete_trigger_are_explicit():
    source = SOURCE.read_text(encoding="utf-8")
    assert "rank2_endpoint_difference" in source
    assert "qualified_rank1_endpoint_difference" in source
    assert "high_resolution_plateau" in source
    assert "difference_beyond_uncertainty" in source


def test_real_main_path_reaches_first_solver_boundary_without_native(tmp_path, monkeypatch):
    """Exercise main(), all reference reads, and the first solver boundary.

    The fake solver raises only at construction.  Therefore a missing global
    name in the real reference-binding/analysis path fails this test before the
    intended boundary, while no provider, solver, Native, or dataset write is
    performed.
    """
    centers = {member: [float(i + 1), float(i) + 0.25] for i, member in enumerate(m41r3.MEMBERS)}
    tiny = np.zeros((4, 4, 2), dtype=np.complex128)
    for band in range(4):
        tiny[band, band, 0] = 1.0

    partial_root = tmp_path / "partial"
    partial_records = partial_root / "records"
    partial_records.mkdir(parents=True)
    for member_index, member in enumerate(m41r3.MEMBERS):
        for repeat in range(3):
            for vertex in range(4):
                value = _record(m41r3, member, member_index, repeat, vertex, "R128_T1E9_M3", m41r3.PARENT_RECORD_SCHEMA, centers[member])
                payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
                metadata = {"complete": True, "payload_sha256": hashlib.sha256(payload).hexdigest(), "payload_size_bytes": len(payload)}
                (partial_records / f"{len(list(partial_records.glob('*.json'))):04d}.json").write_text(json.dumps(metadata), encoding="utf-8")
                (partial_records / f"{len(list(partial_records.glob('*.payload'))):04d}.payload").write_bytes(payload)

    rows_by_dataset: dict[str, list[dict]] = {}
    baseline = []
    for i in range(72):
        member_index = i % 3
        member = m41r3.MEMBERS[member_index]
        value = _record(m41r3, member, member_index, (i // 12) % 3, (i // 3) % 4, "BASELINE", m41r3.BASELINE_SCHEMA, centers[member])
        baseline.append(value)
    rows_by_dataset[m41r3.BASELINE_DATASET_ID] = baseline
    rows_by_dataset[m41r3.M18_DATASET_ID] = [{"schema": m41r3.M18_SCHEMA, "c3_member_identity": m, "geometry_id": "G15", "geometry_role": "AREA_MATCHED_G15", "deterministic": False, "coordinate": centers[m]} for m in m41r3.MEMBERS]
    rows_by_dataset[m41r3.M39R1_DATASET_ID] = [{"schema": m41r3.M39R1_SCHEMA, "c3_member_identity": m, "geometry_id": "G15", "coordinate": centers[m]} for m in m41r3.MEMBERS for _ in range(1)] + [{"schema": m41r3.M39R1_SCHEMA, "c3_member_identity": "IDENTITY", "geometry_id": "G15", "coordinate": centers["IDENTITY"]} for _ in range(11)]
    rows_by_dataset[m41r3.M2_DATASET_ID] = [{"schema": "mephc-berry-c3-pilot-plaquette-v1"} for _ in range(72)]
    manifests = {m41r3.BASELINE_DATASET_ID: m41r3.BASELINE_MANIFEST_SHA256, m41r3.M18_DATASET_ID: m41r3.M18_MANIFEST_SHA256, m41r3.M39R1_DATASET_ID: m41r3.M39R1_MANIFEST_SHA256, m41r3.M2_DATASET_ID: m41r3.M2_MANIFEST_SHA256}

    class Store:
        def __init__(self, root: Path, namespace: dict):
            self.root = partial_root if namespace["work_order_id"] == m41r3.PARTIAL_WORK_ORDER_ID else tmp_path / "new"
            self.records = self.root / "records"
            self.records.mkdir(parents=True, exist_ok=True)
            self.namespace_sha256 = m41r3.PARTIAL_NAMESPACE_SHA256 if namespace["work_order_id"] == m41r3.PARTIAL_WORK_ORDER_ID else "new"
        def put(self, *_args):
            raise AssertionError("dry-run must stop before persistence")
        def finalize(self, *_args):
            raise AssertionError("dry-run must stop before finalization")

    class Job:
        ImmutableDatasetStore = Store
        class BudgetCounter:
            def __init__(self, *_args):
                self.provider_count = 0
                self.solver_count = 0
            def consume_provider(self): self.provider_count += 1
            def consume_solver(self): self.solver_count += 1
        @staticmethod
        def verify_dataset(_state_root, dataset_id):
            return {"manifest_sha256": manifests[dataset_id], "record_count": len(rows_by_dataset[dataset_id]), "record_key_sha256": [str(i) for i in range(len(rows_by_dataset[dataset_id]))]}
        @staticmethod
        def resolve_dataset_record(_state_root, dataset_id, _manifest, key):
            return {"payload": json.dumps(rows_by_dataset[dataset_id][int(key)], separators=(",", ":")).encode()}

    class M39:
        @staticmethod
        def decode_raw(_value): return tiny
    class M38:
        @staticmethod
        def reciprocal_basis(): return np.zeros((2, 2))
        @staticmethod
        def fft_label(index, shape=(128, 128)): return (index % shape[0], index // shape[0])
        @staticmethod
        def transverse_frame(_q): return np.asarray([1.0, 0.0]), np.asarray([0.0, 1.0]), np.asarray([0.0, 0.0, 1.0])

    class DryRunReached(RuntimeError): pass
    class ModeSolver:
        def __init__(self, **_kwargs): raise DryRunReached("FIRST_SOLVER_CALL_BOUNDARY")
    meep = types.ModuleType("meep")
    meep.TE, meep.air = "TE", object()
    meep.Vector3 = lambda x, y, z: (x, y, z)
    meep.cartesian_to_reciprocal = lambda vector, _lattice: vector
    mpb = types.ModuleType("meep.mpb")
    mpb.ModeSolver = ModeSolver
    meep.mpb = mpb
    bandmod = types.ModuleType("mephc.band")
    class Band:
        geo_latt = object()
        def __init__(self, **_kwargs): pass
        def create_unitcell(self, *_args, **_kwargs): return object()
        def create_material_block(self): return []
        def convert_ndarray_to_meep_geo(self, *_args, **_kwargs): return []
    bandmod.Band = Band
    monkeypatch.setitem(sys.modules, "meep", meep)
    monkeypatch.setitem(sys.modules, "meep.mpb", mpb)
    monkeypatch.setitem(sys.modules, "mephc.band", bandmod)
    monkeypatch.setattr(m41r3, "_dynamic_raw", lambda _row, _m39: tiny)
    monkeypatch.setattr(m41r3, "_load", lambda path, _name: Job if "scientific_job" in str(path) else M39 if "m39_" in str(path) else M38)

    bundle_path = tmp_path / "bundle.json"
    result_path = tmp_path / "result.json"
    counters_path = tmp_path / "state" / "counters.json"
    counters_path.parent.mkdir()
    bundle_path.write_text(json.dumps({"work_order_id": "MEPHC-BERRY-C3-M41R3-TEST", "source_commit": "test"}), encoding="utf-8")
    monkeypatch.setenv("MEPHC_INPUT_BUNDLE", str(bundle_path))
    monkeypatch.setenv("MEPHC_RESULT_PATH", str(result_path))
    monkeypatch.setenv("MEPHC_EXECUTION_COUNTERS_PATH", str(counters_path))
    assert m41r3.main() == 0
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["failure_code"] == "FIRST_SOLVER_CALL_BOUNDARY"
    assert result["provider_execution_count"] == 0
    assert result["solver_execution_count"] == 0
