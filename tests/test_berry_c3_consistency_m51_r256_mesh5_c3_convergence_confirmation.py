from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m51_r256_mesh5_c3_convergence_confirmation.py"
SPEC = importlib.util.spec_from_file_location("m51_test_module", SOURCE)
assert SPEC and SPEC.loader
m51 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m51)


def _baseline(failing=("vertex0:band1",)):
    values = {}
    for identity in failing:
        values[identity] = {resolution: {member: [float(index + 1) for index in range(3)] for member in m51.MEMBERS} for resolution in m51.m49r1.RESOLUTIONS}
    return {"frequency": {"failing_identities": list(failing)}, "frequency_src": values}


def _control(shifts):
    values = {}
    for identity, member_shifts in shifts.items():
        values[identity] = {256: {member: [float(index + 1) + member_shifts.get(member, 0.0) for index in range(3)] for member in m51.MEMBERS}}
    return {"frequency_src": values, "gap": {"pass": True}, "subspace": {"pass": True}, "berry2": {"pass": True}, "rank1": {"eligible": True}}


def test_mesh5_graph_has_exactly_36_unique_requests_and_only_mesh5():
    centers = {member: (float(index), float(index + 1)) for index, member in enumerate(m51.MEMBERS)}
    original = m51.m41r3._plaquette_vertices
    try:
        m51.m41r3._plaquette_vertices = lambda _center, _index: ([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)], None)
        graph = m51._mesh_graph(centers, "sha")
    finally:
        m51.m41r3._plaquette_vertices = original
    assert len(graph) == 36
    assert len({row["request_key_sha256"] for row in graph}) == 36
    assert {row["configuration_id"] for row in graph} == {"R256_T1E9_M5"}
    assert {row["mesh_size"] for row in graph} == {5}
    assert {row["mode_count"] for row in graph} == {65536}
    assert {tuple(row["fft_shape"]) for row in graph} == {(256, 256)}


def test_common_mode_mesh_shift_is_not_mesh_sensitive():
    baseline = _baseline()
    shifts = {"vertex0:band1": {member: 10.0 for member in m51.MEMBERS}}
    ledger = m51._frequency_mesh_ledger(baseline, _control(shifts))
    assert ledger["mesh35_all_common_mode"] is True
    assert ledger["per_identity"]["vertex0:band1"]["pairs"]["IDENTITY_vs_C3"]["differential35"] == 0.0


def test_strict_differential_rule_distinguishes_mixed_response():
    baseline = _baseline()
    members = m51.MEMBERS
    control = _control({"vertex0:band1": {members[0]: 5.0, members[1]: 0.0, members[2]: 0.0}})
    ledger = m51._frequency_mesh_ledger(baseline, control)
    assert ledger["mesh35_any_sensitive"] is True
    assert m51._classify(ledger, {"all_pass": False}, control)[0] == "R256_M3_M5_MIXED_FREQUENCY_MESH_RESPONSE"


def test_equality_at_uncertainty_boundary_is_common_mode():
    baseline = _baseline()
    control = _control({"vertex0:band1": {member: 0.0 for member in m51.MEMBERS}})
    ledger = m51._frequency_mesh_ledger(baseline, control)
    for pair in ledger["per_identity"]["vertex0:band1"]["pairs"].values():
        assert pair["mesh35_common_mode"] is True


def test_entrypoint_keeps_mesh5_and_native_after_gate_only():
    text = SOURCE.read_text(encoding="utf-8")
    assert m51.RESULT_SCHEMA in text
    assert m51.DATASET_SCHEMA in text
    assert "mesh_size=MESH_SIZE" in text
    assert text.index("authorized =") < text.index("import meep as mp")
    assert "mpb.ModeSolver" in text
    assert "R288" not in text
