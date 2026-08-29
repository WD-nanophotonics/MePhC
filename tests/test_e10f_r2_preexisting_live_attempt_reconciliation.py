from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "audit/e10f/e10f_r2_preexisting_live_attempt_reconciliation.py"


def load_module():
    spec = importlib.util.spec_from_file_location("e10f_r2_reconciliation", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_failure_classifier_requires_completed_solver_and_post_solve_validation():
    module = load_module()
    result = module.classify_failure(
        "Finished solving for bands 1 to 6\ntmfreqs:",
        "LocalAffineProviderError: LOCAL_AFFINE_KAPPA_BINDING_MISMATCH",
        'snapshot.provenance.get("mpb_reciprocal_k_point")',
        "snapshot = provider.solve(spec)\nrecord = store.put(key, payload, record_identity)",
    )
    assert result == "D_SNAPSHOT_EXTRACTION_SUCCEEDED_POST_SOLVE_PROVIDER_VALIDATION_FAILED"


def test_reconciliation_script_is_solver_free_and_does_not_load_live_backends():
    module = load_module()
    source = SCRIPT.read_text(encoding="utf-8")
    assert "import meep" not in source
    assert "from meep" not in source
    assert "mpiexec" not in source
    assert module.NATIVE_RUN_ID == "MEPHC-NATIVE-10ea7acae05629a43bc66460"
