from __future__ import annotations

import copy
import importlib.util
import json
import py_compile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "audit" / "local_affine" / "p98_third_scale_solver_precision_12_record_binding_plan.json"
TARGET = ROOT / "audit" / "local_affine" / "third_scale_solver_precision_solver_free_comparison.py"


def _module():
    spec = importlib.util.spec_from_file_location("p98_reducer", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _identity(module, group, record):
    graph_sha = module.graph_sha256()
    return {
        "state_id": record["state_id"], "role": record["role"], "public_q": record["public_q"], "s": record["s"],
        "canonical_state_identity": {"public_q": record["public_q"], "s": record["s"], "geometry_digest": "same", "eigensolver_tolerance": group["solver_configuration"]["eigensolver_tolerance"]},
        "reciprocal_metadata": [0.0, 0.0, 0.0], "reference_cell_contract_sha256": "r" * 64,
        "solver_configuration": group["solver_configuration"], "science_source_commit": group["science_source_commit"],
        "request_graph_sha256": graph_sha, "payload_sha256": "a" * 64, "normalized_vector_digest": "v" * 64,
    }


def _bundle(module, plan):
    descriptors = []
    for group in plan["groups"].values():
        for record in group["records"]:
            descriptors.append({
                "dataset_id": group["dataset_id"], "manifest_sha256": group["manifest_sha256"],
                "record_key_sha256": record["record_key_sha256"], "payload_sha256": "a" * 64,
                "payload_size_bytes": 0, "identity": _identity(module, group, record), "payload_file": "payload.bin",
            })
    return {"datasets": descriptors}


def test_binding_plan_has_two_exact_six_record_groups():
    module = _module()
    plan = module.load_binding_plan()
    assert plan["record_count"] == plan["unique_record_key_count"] == 12
    assert set(plan["groups"]) == {"baseline_1e7", "tight_1e9"}
    assert all(len(group["records"]) == 6 for group in plan["groups"].values())
    assert module.graph_sha256() == plan["request_graph_sha256"]
    assert {record["state_id"] for group in plan["groups"].values() for record in group["records"]} == {f"STATE_{index:02d}" for index in range(14, 20)}


def test_all_keys_are_bound_to_their_own_group_work_order():
    module = _module()
    plan = module.load_binding_plan()
    for group in plan["groups"].values():
        for record in group["records"]:
            assert record["record_key_sha256"] == module.derive_record_key_sha256(group["work_order_id"], record)


def test_correct_twelve_descriptor_set_and_pair_identity_pass_validation():
    module = _module()
    plan = module.load_binding_plan()
    assert module.validate_runtime_contract(_bundle(module, plan), plan) is None


def test_cross_group_substitution_is_rejected_without_payload_access():
    module = _module()
    plan = module.load_binding_plan()
    bundle = _bundle(module, plan)
    bundle["datasets"][0]["dataset_id"] = plan["groups"]["tight_1e9"]["dataset_id"]
    with pytest.raises(ValueError, match="P98_DESCRIPTOR_DATASET_MISMATCH"):
        module.validate_runtime_contract(bundle, plan)


def test_direct_reverse_diagnostic_keeps_phase_and_induced_omega_rules():
    module = _module()
    forward = SimpleNamespace(phase=0.2, omega_qs=-0.4, signed_area_qs=0.5, minimum_link_singular_value=0.9, maximum_link_principal_angle=0.2)
    reverse = SimpleNamespace(phase=-0.2, omega_qs=0.4, signed_area_qs=0.5, minimum_link_singular_value=0.9, maximum_link_principal_angle=0.2)
    diagnostics = module._reverse_diagnostics("baseline_qx", forward, reverse)
    assert diagnostics["forward_wilson_phase_baseline_qx"] == 0.2
    assert diagnostics["reverse_wilson_phase_baseline_qx"] == -0.2


def test_fidelity_is_gauge_invariant_magnitude_only():
    module = _module()
    reference = SimpleNamespace(compatibility_key=lambda: (64, (64, 64)))
    identity = SimpleNamespace(reference_cell=reference)
    left = SimpleNamespace(identity=identity, ambient_dimension=2, rank=1, vector_for_band=lambda _: np.array([1.0 + 0j, 0j]))
    right = SimpleNamespace(identity=identity, ambient_dimension=2, rank=1, vector_for_band=lambda _: np.array([-1.0 + 0j, 0j]))
    fidelity, infidelity = module._fidelity(left, right)
    assert fidelity == 1.0
    assert infidelity == 0.0


def test_compare_reports_two_independent_groups_and_descriptive_ratios(monkeypatch):
    module = _module()
    plan = module.load_binding_plan()
    locations = {record["role"]: (tuple(record["public_q"]), record["s"]) for record in plan["groups"]["baseline_1e7"]["records"]}
    reference = SimpleNamespace(compatibility_key=lambda: (64, (64, 64)))
    states = {}
    for role, (public_q, s) in locations.items():
        identity = SimpleNamespace(public_q=public_q, s=s, reference_cell=reference)
        states[role] = SimpleNamespace(identity=identity, ambient_dimension=2, rank=1, vector_for_band=lambda _: np.array([1.0 + 0j, 0j]), frequency_for_band=lambda _: 1.0)
    baseline_values = {"omega_qx_s": -0.19123609378280565, "omega_qy_s": 0.00023419912224820208, "domega_ds": 0.009029822613718097, "forward_wilson_phase_baseline_qx": 4.780902344570142e-07, "forward_wilson_phase_baseline_qy": -5.854978056205052e-10}
    baseline_values.update({"reverse_wilson_phase_baseline_qx": -4.780902344570142e-07, "reverse_wilson_phase_baseline_qy": 5.854978056205052e-10})
    baseline_values.update({
        "minimum_link_singular_value_baseline_qx": 0.99, "minimum_link_singular_value_baseline_qy": 0.99,
        "maximum_link_principal_angle_baseline_qx": 0.1, "maximum_link_principal_angle_baseline_qy": 0.1,
    })
    tight_values = dict(baseline_values)
    for field in (
        "forward_wilson_phase_baseline_qx", "forward_wilson_phase_baseline_qy",
        "minimum_link_singular_value_baseline_qx", "minimum_link_singular_value_baseline_qy",
        "maximum_link_principal_angle_baseline_qx", "maximum_link_principal_angle_baseline_qy",
    ):
        tight_values[field.replace("baseline", "tight")] = tight_values.pop(field)
    tight_values["omega_qx_s"] += 1e-6
    tight_values["omega_qy_s"] += 1e-7
    tight_values["domega_ds"] += 1e-7
    monkeypatch.setattr(module, "_group_reduction", lambda _states, prefix: baseline_values if prefix == "baseline" else tight_values)
    result = module.compare_groups(states, states, plan["groups"]["baseline_1e7"], plan["groups"]["tight_1e9"])
    assert result["schema"] == module.RESULT_SCHEMA
    assert result["state_pair_count"] == 6
    assert result["configuration_count"] == 2
    assert result["minimum_statewise_fidelity"] == 1.0
    assert result["solver_sensitivity_to_geometric_refinement_ratio"]["qx_s"] is not None


def test_reducer_compiles_and_remains_solver_free():
    module = _module()
    assert module is not None
    py_compile.compile(str(TARGET), doraise=True)
    source = TARGET.read_text(encoding="utf-8")
    for forbidden in (
        "import meep", "from meep", "LocalAffineStateProvider",
        "MPBLiveSpectralProvider", "resolve_dataset_record", "archived runtime",
        ".solve(",
    ):
        assert forbidden not in source
