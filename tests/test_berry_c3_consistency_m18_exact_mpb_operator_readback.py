"""M18 direct MPB readback safety tests using strict fakes."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit" / "berry_c3_consistency" / "m18_exact_mpb_operator_readback_and_covariance_closure.py"
SPEC = importlib.util.spec_from_file_location("berry_c3_m18", ENTRYPOINT)
assert SPEC and SPEC.loader
M18 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M18)


class Counter:
    def __init__(self):
        self.solver_count = 0
    def consume_solver(self):
        self.solver_count += 1


class StrictSolver:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []
        self.all_freqs = [list(np.linspace(0.1, 0.6, 6))]
    def run_parity(self, *args):
        self.calls.append("run_parity")
        if self.fail:
            raise RuntimeError("fixture solve failure")
    def get_epsilon(self):
        self.calls.append("get_epsilon")
        return np.ones(M18.SHAPE[0] * M18.SHAPE[1])
    def get_efield(self, band, bloch_phase=False):
        self.calls.append(f"E{band}")
        return np.ones((*M18.SHAPE, 3), dtype=np.complex128) * band
    def get_hfield(self, band, bloch_phase=False):
        self.calls.append(f"H{band}")
        return np.ones((*M18.SHAPE, 3), dtype=np.complex128) * (band + 1)
    def get_dfield(self, band, bloch_phase=False):
        self.calls.append(f"D{band}")
        return np.ones((*M18.SHAPE, 3), dtype=np.complex128) * band
    def get_bfield(self, band, bloch_phase=False):
        self.calls.append(f"B{band}")
        return np.ones((*M18.SHAPE, 3), dtype=np.complex128) * (band + 1)
    def run(self, *args, **kwargs):
        raise AssertionError("generic run must not be called")


def member(index):
    return {"member_index": index, "c3_member_identity": ("IDENTITY", "C3", "C3_SQUARED")[index], "request_key_sha256": f"{index:064x}", "coordinate": [0.1 + index, 0.2]}


def test_capture_one_runs_one_parity_and_reads_six_bands_without_provider():
    solver = StrictSolver(); counter = Counter(); record = M18.capture_one(solver, (0.0, 0.0, 0.0), "TE", member(0), counter)
    record["fresh_energy_vectors_bands_1_to_6"] = [[[0.0, 0.0] for _ in range(6)] for _ in range(6)]
    assert counter.solver_count == 1
    assert record["record_id"].startswith("MEPHC-M18-READBACK-")
    assert record["frequencies_bands_1_to_6"] == list(np.linspace(0.1, 0.6, 6))
    assert record["D_field_availability_status"] == record["B_field_availability_status"] == "CAPTURED"
    assert M18._fresh_energy(record).shape == (M18.VECTOR_LENGTH, M18.BANDS)
    assert solver.calls.count("run_parity") == 1
    assert all(not call.startswith("run") or call == "run_parity" for call in solver.calls)


def test_triplet_has_exactly_three_fixed_dispatches_and_no_fourth_state():
    created = []
    def factory(item):
        solver = StrictSolver(); created.append((item["member_index"], solver)); return solver, (0.0, 0.0, 0.0), "TE"
    counter = Counter(); records = M18.capture_triplet([member(0), member(1), member(2)], factory, counter)
    assert len(records) == 3 and counter.solver_count == 3
    assert [index for index, _ in created] == [0, 1, 2]
    assert all(solver.calls.count("run_parity") == 1 for _, solver in created)


def test_run_failure_is_bounded_and_does_not_call_fields_after_failed_solve():
    solver = StrictSolver(fail=True); counter = Counter()
    try:
        M18.capture_one(solver, (0.0, 0.0, 0.0), "TE", member(0), counter)
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected fixture failure")
    assert counter.solver_count == 1
    assert solver.calls == ["run_parity"]


def test_record_identity_is_stable_and_material_or_member_changes_identity():
    first = M18.capture_one(StrictSolver(), (0.0, 0.0, 0.0), "TE", member(0), Counter())
    first["fresh_energy_vectors_bands_1_to_6"] = [[[0.0, 0.0] for _ in range(6)] for _ in range(6)]
    reordered = {key: first[key] for key in reversed(list(first))}
    assert M18._record_id(first) == M18._record_id(reordered) == first["record_id"]
    second = M18.capture_one(StrictSolver(), (0.0, 0.0, 0.0), "TE", member(1), Counter())
    assert first["record_id"] != second["record_id"]


def test_strict_recovery_decoder_uses_actual_legacy_6_by_6_payload_plus_e_h_blocks():
    record = M18.capture_one(StrictSolver(), (0.0, 0.0, 0.0), "TE", member(0), Counter())
    record["fresh_energy_vectors_bands_1_to_6"] = [[[float(band), float(component)] for component in range(6)] for band in range(6)]
    matrix = M18.decode_persisted_energy_vectors(record)
    assert matrix.shape == (M18.VECTOR_LENGTH, M18.BANDS)
    assert M18._validate_old_energy_payload(record["fresh_energy_vectors_bands_1_to_6"])["element_count_at_old_decoder_level"] == 36


def test_recovery_decoder_rejects_arbitrary_or_incomplete_energy_layout():
    record = M18.capture_one(StrictSolver(), (0.0, 0.0, 0.0), "TE", member(0), Counter())
    record["fresh_energy_vectors_bands_1_to_6"] = [[[0.0, 0.0]] for _ in range(6)]
    try:
        M18.decode_persisted_energy_vectors(record)
    except M18.M18Error:
        pass
    else:
        raise AssertionError("incomplete legacy payload must be rejected")


def test_residual_row_schema_is_canonical_and_explicit():
    row = M18._constitutive_residual(
        np.ones((*M18.SHAPE, 3), dtype=np.complex128),
        np.ones((*M18.SHAPE, 3), dtype=np.complex128),
        np.ones(M18.SHAPE),
        0.2,
        (0.0, 0.0),
        state_identity="IDENTITY",
        band_index=1,
    )
    assert tuple(row) == M18.RESIDUAL_ROW_KEYS
    assert row["state_identity"] == "IDENTITY" and row["band_index"] == 1
    assert all(np.isfinite(row[key]) for key in M18.RESIDUAL_ROW_KEYS[2:])


@pytest.mark.parametrize("bad_row", [
    {"state_identity": "IDENTITY", "band_index": 1, "curlH_residual": 0.0, "maxwell_residual": 0.0},
    {"state_identity": "IDENTITY", "band_index": 1, "curlE_residual": float("nan"), "curlH_residual": 0.0, "maxwell_residual": 0.0},
    {"state_identity": "IDENTITY", "band_index": 1, "curlE_residual": 0.0, "curlH_residual": 0.0, "maxwell_residual": 0.0, "extra": 1},
])
def test_residual_row_validation_rejects_missing_nonfinite_or_malformed_rows(bad_row):
    with pytest.raises(M18.M18Error):
        M18._validate_residual_row(bad_row)


def test_recovered_record_result_for_completes_with_canonical_rows(monkeypatch):
    records = [M18.capture_one(StrictSolver(), (0.0, 0.0, 0.0), "TE", member(index), Counter()) for index in range(3)]
    m12 = []
    m12_module = M18._m12()
    for record in records:
        record["fresh_energy_vectors_bands_1_to_6"] = [[[float(band), float(component)] for component in range(6)] for band in range(6)]
        m12.append({
            "request_key_sha256": record["request_key_sha256"],
            "frequencies_bands_1_to_6": record["frequencies_bands_1_to_6"],
            "normalized_vectors_bands_1_to_6": m12_module.encode_bands(M18.decode_persisted_energy_vectors(record)),
        })
    monkeypatch.setattr(M18, "_material_c3", lambda _: {"exact_runtime_epsilon_grid_c3_residual_max": 0.0, "exact_runtime_material_c3_covariance_status": "EXACT_ZERO"})
    monkeypatch.setattr(M18, "_covariance", lambda _: {"c3_transformed_fresh_state_maxwell_residual_max": 0.0, "operator_intertwining_residual_max": 0.0, "fresh_rank2_c3_minimum_overlap_singular_value": 1.0, "fresh_rank2_c3_maximum_principal_angle": 0.0, "fresh_rank2_c3_covariance_failure_count": 0})
    result = M18.result_for(records, {"dataset_id": "d", "manifest_sha256": "m"}, m12, [], Counter())
    assert result["status"] == "PASS"
    assert len(result["fresh_residual_rows"]) == len(result["archived_residual_rows"]) == 3
    assert all(len(rows) == M18.BANDS for rows in result["fresh_residual_rows"])
    assert result["residual_contract_root_cause"]


def test_actual_child_emits_structured_failure_without_input_bundle(tmp_path):
    output = tmp_path / "result.json"
    env = os.environ.copy()
    env.update({"MEPHC_INPUT_BUNDLE": str(tmp_path / "missing.json"), "MEPHC_RESULT_PATH": str(output), "MEPHC_EXECUTION_COUNTERS_PATH": str(tmp_path / "counters.json")})
    completed = subprocess.run([sys.executable, str(ENTRYPOINT)], env=env, capture_output=True, text=True, check=False)
    assert completed.returncode == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["schema"] == M18.RESULT_SCHEMA and result["status"] == "FAIL_CLOSED"
    assert result["provider_execution_count"] == result["solver_execution_count"] == result["dataset_record_count"] == 0
