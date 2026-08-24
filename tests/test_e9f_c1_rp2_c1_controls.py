from __future__ import annotations
from pathlib import Path
import inspect
import sys
import numpy as np
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from audit.e9f import run_e9f_c1_rp2_c1 as rp2
from mephc.eigenspace import RawEigenstate
from mephc.spectral_association import RawAssociationThresholds


class Raw:
    def __init__(self, bad_full=False, bad_pair=False):
        self.k_point=(0.0,0.0)
        self.frequencies=tuple(float(i+1) for i in range(6))
        self.normalized_vectors=tuple(np.eye(6,dtype=np.complex128)[:,i] for i in range(6))
        self.raw_eigenstates=tuple(RawEigenstate(self.k_point,i,self.frequencies[i],self.normalized_vectors[i],{}) for i in range(6))
        self.gram_matrix=np.eye(6,dtype=np.complex128)
        if bad_full: self.gram_matrix[0,1]=self.gram_matrix[1,0]=0.25
        if bad_pair: self.gram_matrix[2,3]=self.gram_matrix[3,2]=0.25
        self.max_normalization_error=0.0
        self.max_off_diagonal_gram=float(np.max(np.abs(self.gram_matrix-np.diag(np.diag(self.gram_matrix)))))
        self.orthogonality_status="MPB_H_ENVELOPE_QUALIFIED" if not bad_full else "MPB_H_ENVELOPE_UNQUALIFIED"
        self.orthogonality_tolerance=1e-10


def values(raw):
    return [{"raw":raw,"gram_diagnostics":rp2._impl._gram_diagnostics(raw),"record":{"EVALUATED_Q":[0.0,0.0]}} for _ in range(4)]


def test_fixed_matrix_and_contract():
    contract=rp2.load_execution_contract(ROOT)
    rows=rp2.build_plan(ROOT)
    assert contract["l0"]["zero_based_window"] == [1,2,3,4]
    assert contract["raw_association"]["candidate_window_zero_based"] == [2,3]
    assert len(rows)==12 and len(rp2.matrix_entry_keys())==24


def test_l0_uses_bands_1_to_4_zero_based_1_to_4_window():
    result=rp2._impl._l0(type("S",(),{"frequencies":(10.,20.,30.,40.,50.,60.)})())
    assert result["ordered_frequencies_bands_1_2_3_4"] == [20.,30.,40.,50.]
    assert result["gap_12"] == 10. and result["internal_gap_23"] == 10. and result["upper_external_gap_34"] == 10.
    assert result["raw_frequencies_all_six_bands"] == [10.,20.,30.,40.,50.,60.]


def test_full_six_failure_does_not_block_selected_pair_association():
    maps,evidence=rp2._impl._associate_vertices(values(Raw(bad_full=True)), RawAssociationThresholds(0.5,0.05,0.05,1e-10))
    assert maps == [{2:2,3:3}]*4
    assert all(item["candidate_window_zero_based"] == [2,3] for item in evidence)
    assert evidence[0]["left_pair_gram"]["full_six_state_max_off_diagonal_gram"] > 0.1
    assert evidence[0]["left_pair_gram"]["selected_pair_max_off_diagonal_gram"] == 0.0


def test_selected_pair_failure_is_fail_closed():
    with pytest.raises(rp2._impl.DiagnosticAdapterPreconditionError, match="SELECTED_PAIR_REPRESENTATION"):
        rp2._impl._associate_vertices(values(Raw(bad_pair=True)), RawAssociationThresholds(0.5,0.05,0.05,1e-10))


def test_l1_is_solver_neutral_shadow_and_not_production_qualified():
    raw=Raw()
    vals=values(raw)
    result=rp2._impl._rank1_level(vals,[{2:2,3:3}]*4,2,None,[{"status":"CLEAR"}],"1/72")
    assert result["status"]=="DIAGNOSTIC_REPORTED"
    assert result["transport_method"]=="solver_neutral_parallel_transport_link"
    assert result["RANK1_RECOVERED"] is False
    assert all(edge["min_singular_value"] >= 1-1e-10 for edge in result["edge_transport"])
    assert result["production_external_gap_context"] == 0.02
    assert "qualify_ordered_path" not in inspect.getsource(rp2._impl._rank1_level)


def test_l2_has_no_rank1_prerequisite_and_uses_pair_only():
    source=inspect.getsource(rp2._impl._rank2_level)
    assert "_path_diagnostic" not in source
    assert "rank1_prerequisite" in source and "selected=" in source


def test_parent_import_is_solver_free():
    assert not any(name=="meep" or name.startswith("meep.") or name=="mpb" or name.startswith("mpb.") for name in sys.modules)


def test_canary_stops_on_adapter_failure():
    row=rp2.build_plan(ROOT)[0]
    entry={"association":[{"status":"NOT_AVAILABLE_WITH_REASON","unavailability_class":"ADAPTER_OR_API_PRECONDITION_FAILURE"}],"association_candidate_window_zero_based":[2,3],"L2":{"pair_zero_based":[2,3]}}
    payload={"stencils":{"1/72":entry,"1/144":entry}}
    with pytest.raises(rp2.CampaignRuntimeError,match="CANARY_ADAPTER"):
        rp2._impl._canary_gate(payload,row)
