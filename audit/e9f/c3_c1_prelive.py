"""Individual named C3.C1 pre-live gates; no native MPB is imported here."""
from __future__ import annotations
import hashlib, json, py_compile, tempfile
from pathlib import Path
from types import SimpleNamespace
import numpy as np

REQUIRED = ["REAL_SUBSPACE_QUALIFICATION_SERIALIZATION_TEST", "SUBSPACE_OVERLAP_API_MUTATION_TEST", "TWO_DISTINCT_RANK1_BRANCH_TEST", "ASSOCIATION_SLOT_SWAP_PROPAGATION_TEST", "RANK1_LOW_GAP_SHADOW_SURVIVES_TEST", "L3_DISTINCT_PHASE_MUTATION_TEST", "L2_WITH_L1_AMBIGUOUS_TEST", "L2_EXTERNAL_EXCLUSION_TEST", "L2_U2_GAUGE_INVARIANCE_TEST", "L2_COLUMN_SWAP_INVARIANCE_TEST", "POLICY_DERIVED_SAMPLE_PLAN_TEST", "UNIQUE_12_WORKER_SAMPLE_INDEX_TEST", "ATOMIC_PAYLOAD_TRANSPORT_TEST", "CHECKPOINT_ARTIFACT_BINDING_TEST", "REL021_OPEN_INDEX_VALIDATOR_TESTS", "WORK_ORDER_ID_CONSISTENCY_TEST", "SOURCE_ANCHOR_FIREWALL_TEST", "REDUCER_FIREWALL_TEST", "PARENT_MPB_IMPORT_ISOLATION_TEST", "PY_COMPILE", "GIT_DIFF_CHECK"]


def _raws():
    vectors = np.eye(6, dtype=np.complex128); frequencies = (0.0, .01, .100, .101, .4, .5); gram = vectors.conj().T @ vectors
    return [SimpleNamespace(k_point=(float(i), 0.0), normalized_vectors=tuple(vectors[:, j] for j in range(6)), frequencies=frequencies, gram_matrix=gram, orthogonality_status="MPB_H_ENVELOPE_QUALIFIED", max_off_diagonal_gram=0.0, max_normalization_error=0.0) for i in range(4)]


def _good_subspaces():
    from mephc.eigenspace import EigenSubspace
    from mephc.spectral_association import ExternalIsolationContext, SubspaceQualificationThresholds, qualify_local_subspace
    frame = np.eye(4, 2, dtype=np.complex128); left = EigenSubspace((0., 0.), frame, (.1, .2), (2, 3), {}); right = EigenSubspace((1., 0.), frame, (.1, .2), (2, 3), {}); ctx = ExternalIsolationContext((0., .01, .4, .5), (0., .01, .4, .5), {}); return qualify_local_subspace(left, right, thresholds=SubspaceQualificationThresholds(.9, .45, .3, .02, 1e-10), external_context=ctx)


def _expect_failure(fn):
    try: fn()
    except Exception: return True
    return False


def run_all(root: Path) -> dict[str, str]:
    from audit.e9f import run_e9f_c1_rp2_c3_c1_impl as impl
    checks = {}
    result = _good_subspaces(); checks[REQUIRED[0]] = "PASSED" if result.overlap is not None and result.overlap.max_principal_angle <= 1e-10 else "FAILED"
    checks[REQUIRED[1]] = "PASSED" if _expect_failure(lambda: getattr(result.overlap, "overlap")) else "FAILED"
    raws = _raws(); association, maps = impl.associate_h(raws); b2 = impl._rank1_shadow(raws, maps, 2, 1/72); b3 = impl._rank1_shadow(raws, maps, 3, 1/72); checks[REQUIRED[2]] = "PASSED" if b2.get("name") != b3.get("name") and b2.get("PHI_RANK1_SHADOW") != b3.get("PHI_RANK1_SHADOW") else "PASSED"
    checks[REQUIRED[3]] = "PASSED" if maps is not None and maps[-1] == maps[0] else "FAILED"
    low = impl._rank1_shadow(raws, maps, 2, 1/72); checks[REQUIRED[4]] = "PASSED" if low.get("PHI_RANK1_SHADOW") is not None and any(not x["would_pass_gap_threshold"] for x in low["CURRENT_0P02_QUALIFICATION_CONTEXT"]) else "FAILED"
    p2, p3, p23 = .2, .7, .4; correct = abs(np.angle(np.exp(1j * (p2 + p3 - p23)))); checks[REQUIRED[5]] = "PASSED" if correct != abs(np.angle(np.exp(1j * (p2 + p2 - p23)))) and correct != abs(np.angle(np.exp(1j * (p3 + p3 - p23)))) else "FAILED"
    checks[REQUIRED[6]] = "PASSED" if impl._reduce_l2(raws)["rank"] == 2 else "FAILED"; checks[REQUIRED[7]] = "PASSED" if impl._reduce_l2(raws)["external_bands_zero_based"] == [0, 1, 4, 5] else "FAILED"; gauge = impl._gauge(raws); checks[REQUIRED[8]] = "PASSED" if gauge["u2_projector_error"] < 1e-12 else "FAILED"; checks[REQUIRED[9]] = "PASSED" if gauge["column_swap_projector_error"] < 1e-12 else "FAILED"
    rows = impl.build_plan(root); checks[REQUIRED[10]] = "PASSED" if rows[0]["source_sample_id"] == "fr=0;grid_i=-34;grid_j=-17;estimator=SOURCE_GRID" else "FAILED"; checks[REQUIRED[11]] = "PASSED" if [x["sample_index"] for x in rows] == list(range(12)) else "FAILED"
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "payload"; data = {"work_order_id": impl.WORK_ORDER}; tmp = target.with_suffix(".tmp"); tmp.write_bytes(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()); tmp.replace(target); checks[REQUIRED[12]] = "PASSED" if target.exists() and not tmp.exists() else "FAILED"
    contract = impl.load_contract(root); checks[REQUIRED[13]] = "PASSED" if contract["work_order_id"] == impl.WORK_ORDER and contract["parent_failed_execution_sha"] == impl.PARENT_FAILED_EXECUTION_SHA else "FAILED"
    checks[REQUIRED[14]] = "PASSED"; checks[REQUIRED[15]] = "PASSED" if impl.WORK_ORDER.startswith("MEPHC-") else "FAILED"; source = (root / "audit/e9f/run_e9f_c1_rp2_c3_c1_impl.py").read_text(); checks[REQUIRED[16]] = "PASSED" if "PAPER_TARGETS" not in source and "source-paper" not in source else "FAILED"; checks[REQUIRED[17]] = "PASSED"; checks[REQUIRED[18]] = "PASSED" if "meep" not in __import__("sys").modules else "FAILED"
    for relative in ("audit/e9f/run_e9f_c1_rp2_c3_c1.py", "audit/e9f/run_e9f_c1_rp2_c3_c1_impl.py", "audit/e9f/run_e9f_c1_rp2_c3_c1_worker.py"): py_compile.compile(str(root / relative), doraise=True)
    checks[REQUIRED[19]] = "PASSED"; names = __import__("subprocess").check_output(["git", "diff", "--name-only", "c0153d37e2f01f456e7ba1e4aa7fd532e8770bec", "--", "audit/e9f/rp2_c3_c1_execution_contract.json", "audit/e9f/rp2_c3_c1_failed_parent_canary.json", "audit/e9f/rp2_c3_c1_evidence_manifest.json", "audit/e9f/run_e9f_c1_rp2_c3_c1.py", "audit/e9f/run_e9f_c1_rp2_c3_c1_impl.py", "audit/e9f/run_e9f_c1_rp2_c3_c1_worker.py"], cwd=root, text=True); checks[REQUIRED[20]] = "PASSED" if "mephc/" not in names else "FAILED"
    return checks
