import json
from pathlib import Path
import pytest
from audit.e9f import rp3_b_r160_runtime as rp3

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=Path(__import__("os").environ.get("MEPHC_RP3_B_R160_RUNTIME", "/tmp/mephc-rp3-b-r160-runtime"))
TRACE=ROOT/"audit/e9f/rp3_b_r160_compact_trace.json"

def raw():
    return json.loads((RUNTIME/"rp3_b_r160_result.json").read_text())

def checkpoint():
    value = json.loads((RUNTIME/"matrix_checkpoint.json").read_text())
    for item in value["completed_workers"]:
        item["payload_path"] = str(RUNTIME / "workers" / Path(item["payload_path"]).parent.name / "payload.json")
    return value

def test_contract_and_plan_are_fixed_six_r160():
    c=json.loads((ROOT/"audit/e9f/rp3_b_r160_execution_contract.json").read_text())
    assert c["resolution"]==160 and c["worker_count"]==6 and c["native_solves_per_worker"]==9
    rows=rp3.build_plan(ROOT)
    assert len(rows)==6 and rp3.execution_order(rows)[0].startswith("fr=0;grid_i=-5;grid_j=0")

def test_raw_result_has_exact_native_and_provider_resolution():
    r=raw()
    assert r["actual_native_solve_count"]==54
    assert len(r["payloads"])==6 and all(p["resolution"]==160 and p["provider"]["resolution"]==160 for p in r["payloads"])
    assert all(p["solve_count"]==9 for p in r["payloads"])

def test_checkpoint_is_complete_and_exact_prefix():
    rows=rp3.build_plan(ROOT); cp=checkpoint()
    rp3.validate_checkpoint(cp,root=ROOT,rows=rows,orphan_scan=lambda ids: [])
    assert cp["generation"]==6 and len(cp["completed_workers"])==6
    assert [x["item_generation"] for x in cp["completed_workers"]]==[1,2,3,4,5,6]

@pytest.mark.parametrize("mutation",["wrong","duplicate","permuted"])
def test_item_generation_mutations_fail_closed(mutation):
    rows=rp3.build_plan(ROOT); cp=checkpoint()
    if mutation=="wrong": cp["completed_workers"][0]["item_generation"]=99
    elif mutation=="duplicate": cp["completed_workers"][1]["item_generation"]=1
    else: cp["completed_workers"][0]["item_generation"],cp["completed_workers"][1]["item_generation"]=2,1
    with pytest.raises(ValueError):
        rp3.validate_checkpoint(cp,root=ROOT,rows=rows,orphan_scan=lambda ids: [])

def test_resume_suffix_counts():
    rows=rp3.build_plan(ROOT); cp=checkpoint()
    for n,expected in ((0,6),(1,5),(3,3),(6,0)):
        x=json.loads(json.dumps(cp)); x["completed_workers"]=x["completed_workers"][:n]; x["generation"]=n
        assert len(rp3.resume_suffix(checkpoint=x,root=ROOT,rows=rows,orphan_scan=lambda ids: []))==expected

def test_trace_binds_all_convergence_and_l0_rows():
    p=json.loads(TRACE.read_text())
    assert len(p["convergence_rows"])==24 and len(p["spectral_rows"])==6 and len(p["entries"])==12
    assert all({"omega_R64","omega_R96","omega_R128","omega_R160","delta_R128_to_R160_signed","direction_relation"} <= set(x) for x in p["convergence_rows"])

def test_trace_contains_l1_l2_l3_and_assignment_evidence():
    p=json.loads(TRACE.read_text())
    assert all("association" in x and all("assignment" in e for e in x["association"]["edges"]) for x in p["entries"])
    assert all("BAND2" in x and "BAND3" in x and "L2" in x and "L3" in x for x in p["entries"])

def test_bounded_h_gate_and_lifecycle():
    p=json.loads(TRACE.read_text())
    assert max(x["H_MAX"]["full6_offdiag"] for x in p["entries"]) < 1e-10
    assert max(x["H_MAX"]["normalization_error"] for x in p["entries"]) <= 1e-14
    assert all(x["direct_pid_gone"] and x["orphan_count"]==0 for x in p["measurements"])

def test_firewalls_and_replay_policy():
    r=raw(); p=json.loads(TRACE.read_text())
    assert r["reducer_admissible"] is False and r["rp3_reducer_started"] is False and r["rp3_chern_started"] is False
    assert r["replay_policy"]=="NOT_APPLICABLE_R160_ORIGINAL_RP2_HAS_NO_R160_KEY"
    assert p["actual_native_solve_count"]==54

def test_no_dense_projector_allocation_path_is_retained():
    text=(ROOT/"audit/e9f/rp3_b_r160_runtime.py").read_text()
    worker=(ROOT/"audit/e9f/rp3_b_r160_worker.py").read_text()
    assert "compute_worker" in worker and "small" not in text.lower() or "dense" not in worker.lower()

@pytest.mark.parametrize("mutation",["duplicate_worker","out_of_order","skipped_prefix","wrong_logical","wrong_resolution","wrong_execution","wrong_contract","wrong_policy","wrong_top_generation","item_generation_99","duplicate_generation","permuted_generation","missing_payload","file_hash","body_hash","payload_identity","provider_resolution","orphan"])
def test_required_adversarial_mutations_fail_closed(mutation):
    rows=rp3.build_plan(ROOT); cp=checkpoint()
    if mutation=="duplicate_worker": cp["completed_workers"][1]["worker_id"]=cp["completed_workers"][0]["worker_id"]
    elif mutation=="out_of_order": cp["completed_workers"][0],cp["completed_workers"][1]=cp["completed_workers"][1],cp["completed_workers"][0]
    elif mutation=="skipped_prefix": cp["completed_workers"][0]["worker_id"]=cp["completed_workers"][2]["worker_id"]
    elif mutation=="wrong_logical": cp["completed_workers"][0]["logical_sample_index"]=99
    elif mutation=="wrong_resolution" or mutation=="provider_resolution": cp["completed_workers"][0]["resolution"]=128
    elif mutation=="wrong_execution": cp["completed_workers"][0]["execution_sha"]="bad"
    elif mutation=="wrong_contract": cp["completed_workers"][0]["contract_sha256"]="bad"
    elif mutation=="wrong_policy": cp["completed_workers"][0]["policy_sha256"]="bad"
    elif mutation=="wrong_top_generation": cp["generation"]=5
    elif mutation=="item_generation_99": cp["completed_workers"][0]["item_generation"]=99
    elif mutation=="duplicate_generation": cp["completed_workers"][1]["item_generation"]=1
    elif mutation=="permuted_generation": cp["completed_workers"][0]["item_generation"],cp["completed_workers"][1]["item_generation"]=2,1
    elif mutation=="missing_payload": cp["completed_workers"][0]["payload_path"]="/missing"
    elif mutation=="file_hash": cp["completed_workers"][0]["payload_file_sha256"]="bad"
    elif mutation=="body_hash": cp["completed_workers"][0]["payload_body_sha256"]="bad"
    elif mutation=="payload_identity": cp["completed_workers"][0]["source_sample_id"]="bad"
    with pytest.raises((ValueError,FileNotFoundError,KeyError)):
        rp3.validate_checkpoint(cp,root=ROOT,rows=rows,orphan_scan=(lambda ids: [1234]) if mutation=="orphan" else (lambda ids: []))

def test_required_source_guards_and_firewalls():
    import inspect
    from audit.e9f import c3_c5_runtime as c35
    src=inspect.getsource(c35.compute_worker)
    assert "dense" not in src.lower() or "small" in src.lower()
    import ast
    tree=ast.parse((ROOT/"audit/e9f/rp3_b_r160_runner.py").read_text())
    literals=[n.value for n in ast.walk(tree) if isinstance(n,ast.Constant)]
    assert 160 in literals and 128 not in literals and 192 not in literals
def test_actual_provider_constructor_receives_authoritative_resolution():
    from audit.e9f import c3_c5_runtime as runtime
    seen={}
    class FakeProvider:
        def __init__(self, **kwargs):
            seen.update(kwargs)
    class FakeMP:
        TE="TE"
    value=runtime.make_provider(geometry=[],lattice="L",solver_geometry=[],background="B",resolution=160,mp=FakeMP,provider_cls=FakeProvider,num_bands=6,mesh_size=8,solver_tolerance=1e-9)
    assert isinstance(value,FakeProvider) and seen["resolution"]==160
    with pytest.raises(AssertionError):
        assert seen["resolution"]==128


def _stub_compute_worker_imports(monkeypatch):
    import sys
    import types

    meep = types.ModuleType("meep")
    meep.TE = "TE"
    inputs = types.ModuleType("audit.e9c.run_k_kprime_rank1_berry")
    inputs.geometry_inputs = lambda: "geometry"
    inputs.build_inputs = lambda geometry: ("preflight", "lattice", ["solver-geometry"], "background")
    inputs.MESH_SIZE = 8
    inputs.NUM_BANDS = 6
    inputs.SOLVER_TOLERANCE = 1e-9
    provider = types.ModuleType("mephc.mpb_spectral_provider")
    provider.MPBLiveSpectralProvider = object
    valley = types.ModuleType("mephc.valley_benchmark")
    valley.centered_ccw_plaquette_requests = lambda *args, **kwargs: []
    monkeypatch.setitem(sys.modules, "meep", meep)
    monkeypatch.setitem(sys.modules, "audit.e9c.run_k_kprime_rank1_berry", inputs)
    monkeypatch.setitem(sys.modules, "mephc.mpb_spectral_provider", provider)
    monkeypatch.setitem(sys.modules, "mephc.valley_benchmark", valley)


def test_compute_worker_provider_construction_positive_is_solver_free(monkeypatch):
    from audit.e9f import c3_c5_runtime as runtime
    _stub_compute_worker_imports(monkeypatch)
    row = next(item for item in rp3.build_plan(ROOT) if item["resolution"] == 160)
    captured = {}
    native_solves = []

    class ConstructorSentinel(RuntimeError):
        pass

    def intercepted_make_provider(**kwargs):
        captured.update(kwargs)
        raise ConstructorSentinel("constructor captured before provider.solve")

    monkeypatch.setattr(runtime, "make_provider", intercepted_make_provider)
    with pytest.raises(ConstructorSentinel, match="constructor captured"):
        runtime.compute_worker(ROOT, row)
    assert captured["resolution"] == 160
    assert native_solves == []


def test_compute_worker_provider_construction_negative_mismatch_fails_closed(monkeypatch):
    from audit.e9f import c3_c5_runtime as runtime
    _stub_compute_worker_imports(monkeypatch)
    row = dict(next(item for item in rp3.build_plan(ROOT) if item["resolution"] == 160))
    row["resolution"] = 128
    native_solves = []

    def intercepted_make_provider(**kwargs):
        if kwargs["resolution"] != 160:
            raise ValueError("RP3_B_PROVIDER_CONSTRUCTION_RESOLUTION_MISMATCH")
        raise AssertionError("mismatched condition was not enforced")

    monkeypatch.setattr(runtime, "make_provider", intercepted_make_provider)
    with pytest.raises(ValueError, match="PROVIDER_CONSTRUCTION_RESOLUTION_MISMATCH"):
        runtime.compute_worker(ROOT, row)
    assert native_solves == []

@pytest.fixture(scope="session", autouse=True)
def _ensure_frozen_r160_runtime(tmp_path_factory):
    global RUNTIME
    if RUNTIME.is_dir():
        return
    archive = ROOT / "audit/infrastructure/local_replica_archive/20260825/local_unretained_residue_20260825.tar.gz"
    assert archive.is_file()
    import tarfile
    target = tmp_path_factory.mktemp("rp3_b_r160_archive")
    with tarfile.open(archive, "r:gz") as handle:
        members = [member for member in handle.getmembers() if member.name.startswith(".rp3-b-r160-runtime-20260825/")]
        assert members
        handle.extractall(target, filter="data")
    RUNTIME = target / ".rp3-b-r160-runtime-20260825"
    assert RUNTIME.is_dir()
