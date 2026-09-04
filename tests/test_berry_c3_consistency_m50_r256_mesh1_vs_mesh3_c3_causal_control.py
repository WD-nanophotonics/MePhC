from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m50_r256_mesh1_vs_mesh3_c3_causal_control.py"
SPEC = importlib.util.spec_from_file_location("m50_test_module", SOURCE)
assert SPEC and SPEC.loader
m50 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m50)


def _baseline(failing=("vertex0:band1",)):
    values = {}
    for identity in failing:
        values[identity] = {resolution: {member: [float(index + 1) for index in range(3)] for member in m50.MEMBERS} for resolution in m50.m49r1.RESOLUTIONS}
    return {"frequency": {"failing_identities": list(failing)}, "frequency_src": values, "failing_layers": ["frequency"], "classification": "R256_FREQUENCY_C3_BREAKING", "decision": "BOUND_R256_MESH_DISCRETIZATION_CONTROL", "association": {"unstable": False}}


def _control(shifts):
    values = {}
    for identity, member_shifts in shifts.items():
        values[identity] = {256: {member: [float(index + 1) + member_shifts.get(member, 0.0) for index in range(3)] for member in m50.MEMBERS}}
    return {"frequency_src": values}


def test_mesh_ledger_uses_member_differential_shift_not_absolute_shift():
    baseline = _baseline()
    same = _control({"vertex0:band1": {member: 10.0 for member in m50.MEMBERS}})
    ledger = m50._frequency_mesh_ledger(baseline, same)
    assert ledger["mesh_sensitive"] is False
    pair = ledger["per_identity"]["vertex0:band1"]["pairs"]["IDENTITY_vs_C3"]
    assert pair["differential_shift"] == 0.0
    assert pair["mesh_sensitive"] is False


def test_mesh_classification_requires_strict_excess_over_uncertainty():
    baseline = _baseline()
    members = m50.MEMBERS
    exact = _control({"vertex0:band1": {members[0]: 0.0, members[1]: 0.0, members[2]: 0.0}})
    exact["frequency_src"]["vertex0:band1"][256][members[0]] = [2.0, 2.0, 2.0]
    exact["frequency_src"]["vertex0:band1"][256][members[1]] = [1.0, 1.0, 1.0]
    ledger = m50._frequency_mesh_ledger(baseline, exact)
    assert m50._classify_mesh(ledger)[0] == "R256_FREQUENCY_C3_BREAKING_MESH_INSENSITIVE"

    sensitive = _control({"vertex0:band1": {members[0]: 5.0, members[1]: 0.0, members[2]: 0.0}})
    ledger = m50._frequency_mesh_ledger(baseline, sensitive)
    assert m50._classify_mesh(ledger)[0] == "R256_FREQUENCY_C3_BREAKING_MIXED_MESH_AND_NONMESH"


def test_mesh_graph_is_exactly_36_unique_mesh1_requests(monkeypatch):
    monkeypatch.setattr(m50.m41r3, "_plaquette_vertices", lambda _center, _index: ([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0)], None))
    centers = {member: (float(index), float(index + 1)) for index, member in enumerate(m50.MEMBERS)}
    graph = m50._mesh_graph(centers, "sha")
    assert len(graph) == 36
    assert len({row["request_key_sha256"] for row in graph}) == 36
    assert {row["configuration_id"] for row in graph} == {"R256_T1E9_M1"}
    assert {row["mesh_size"] for row in graph} == {1}
    assert {row["mode_count"] for row in graph} == {65536}
    assert {tuple(row["fft_shape"]) for row in graph} == {(256, 256)}


def test_prenative_empty_failure_set_routes_without_mesh_acquisition():
    ledger = {"baseline_failing_frequency_identities": [], "per_identity": {}, "mesh_sensitive": False}
    assert m50._classify_mesh(ledger) == ("PRENATIVE_M49R1_REROUTE_NO_MESH_ACQUISITION", "USE_PRENATIVE_REPRODUCED_M49R1_CONCRETE_DECISION")


def test_entrypoint_keeps_native_import_after_pre_native_gate_and_forbids_r288():
    text = SOURCE.read_text(encoding="utf-8")
    assert m50.RESULT_SCHEMA in text
    assert "R288" not in text
    assert '"mesh_size": 1' in text
    assert text.index("authorized =") < text.index("import meep as mp")
    assert '"native_invocation_count": 1' in text
    assert "mpb.ModeSolver" in text
