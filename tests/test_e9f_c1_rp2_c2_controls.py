from __future__ import annotations
from pathlib import Path
import inspect
import subprocess
import sys
import numpy as np
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from audit.e9f import run_e9f_c1_rp2_c2 as c2
from mephc.eigenspace import RawEigenstate


class FakeRaw:
    def __init__(self, overlap=False):
        self.k_point=(0.0,0.0)
        self.frequencies=tuple(float(i+1) for i in range(6))
        basis=np.zeros((12,6),dtype=np.complex128)
        for i in range(6):
            basis[i,i]=1/np.sqrt(2)
            basis[i+6,i]=1/np.sqrt(2)
        if overlap:
            basis[:,3]=basis[:,2]
            basis[:,3]=basis[:,3]/np.linalg.norm(basis[:,3])
        self.normalized_vectors=tuple(basis[:,i] for i in range(6))
        self.raw_eigenstates=tuple(RawEigenstate(self.k_point,i,self.frequencies[i],self.normalized_vectors[i],{}) for i in range(6))
        self.gram_matrix=np.column_stack(self.normalized_vectors).conj().T @ np.column_stack(self.normalized_vectors)
        self.max_normalization_error=0.0
        self.max_off_diagonal_gram=float(np.max(np.abs(self.gram_matrix-np.diag(np.diag(self.gram_matrix)))))
        self.orthogonality_status="MPB_H_ENVELOPE_QUALIFIED"
        self.orthogonality_tolerance=1e-10


def test_exact_scope_and_thresholds():
    contract=c2.load_execution_contract(ROOT)
    rows=c2.build_plan(ROOT)
    assert len(rows)==2 and {row["resolution"] for row in rows}=={64,96}
    assert contract["primary"]["total_solves"]==18 and contract["control"]["total_solves"]==2
    assert c2.ASSOCIATION_THRESHOLD == {"probability_threshold":0.5,"margin_threshold":0.05,"assignment_margin_threshold":0.05,"validation_tolerance":1e-10}


def test_agents_md_exact_restore():
    expected=subprocess.check_output(["git","show","ea742a7f713255741de39eb2daec92813ee71917:AGENTS.md"],cwd=ROOT)
    assert (ROOT/"AGENTS.md").read_bytes()==expected


def test_vector_split_and_component_normalization():
    vector=np.array([3+0j,4+0j,1+0j,2+0j])
    e,h=c2._impl._split_vector(vector)
    eu,en=c2._impl._unit(e); hu,hn=c2._impl._unit(h)
    assert len(e)==2 and len(h)==2
    assert en==pytest.approx(25.0) and hn==pytest.approx(5.0)
    assert np.linalg.norm(eu)==pytest.approx(1.0)


def test_gram_decomposition_closure_and_pair_metrics():
    raw=FakeRaw()
    metric=c2._impl._point_metrics(raw,{"NOMINAL_Q":[0.,0.],"MANIFEST_Q":[0.,0.],"EVALUATED_Q":[0.,0.],"physical_cache_identity":"x"})
    assert metric["GRAM_DECOMPOSITION_CLOSURE_PASS"] is True
    assert metric["GRAM_DECOMPOSITION_CLOSURE_MAX"] <= 1e-12
    assert metric["PAIR_G_EH_23"]["magnitude"] == pytest.approx(0.0)
    assert len(metric["PAIR_G_EH_EIGENVALUES"])==2


def test_combined_eh_precondition_failure_is_data():
    raw=FakeRaw(overlap=True)
    vertices=[{"raw":raw} for _ in range(4)]
    result=c2._impl._association_probe(vertices,"COMBINED_EH")
    assert result["precondition_pass_edges"] < 4
    assert result["clear_edges"] == 0
    assert all(edge["failure_reason"] for edge in result["edges"])


def test_no_physics_transport_or_reducer_imports_in_probe():
    source=inspect.getsource(c2._impl)
    assert "mephc.wilson_geometry" not in source
    assert "berry_curvature" not in source
    assert "from mephc.chern" not in source


def test_failure_metric_schema_is_explicit():
    source=inspect.getsource(c2._impl.validate_worker_payload)
    assert "MEASURED_VALUE" in source and "THRESHOLD_VALUE" in source


def test_parent_import_is_solver_free():
    assert not any(name=="meep" or name.startswith("meep.") or name=="mpb" or name.startswith("mpb.") for name in sys.modules)
