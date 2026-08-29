from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "audit/e10d/e10d_provenance_reconciliation.py"


def load_module():
    spec = importlib.util.spec_from_file_location("e10d_provenance_reconciliation", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reconciliation_binds_distinct_provenance_roles_without_science_execution():
    module = load_module()
    result = module.build_reconciliation()

    assert result["commit_lineage_status"] == "PASS"
    assert result["authoritative_science_source_status"] == "PASS"
    assert result["embedded_final_origin_status"] == "NONAUTHORITATIVE_LEGACY_BASE_BOUND"
    assert result["downstream_provenance_binding_status"] == "PASS"
    assert result["e10d_scientific_kernel_status"] == "ACCEPTED"
    assert result["e10d_provenance_reconciliation_status"] == "PASS"
    assert result["e10d_ready_for_e10e"] is True
    assert result["native_invocation_count"] == 0
    assert result["provider_executions"] == 0
    assert result["solver_executions"] == 0
    assert result["mpb_execution"] is False
    assert result["kernel_bytes_unchanged"] is True
    assert result["validation_bytes_unchanged"] is True


def test_reconciliation_preserves_explicit_implementation_and_execution_identities():
    module = load_module()
    result = module.build_reconciliation()

    assert result["e10d_base_input_commit"] == "35818629f9947cf7455d364ea2ebfb0f111bcd48"
    assert result["e10d_kernel_implementation_commit"] == "b5e40fa08b27075fda08b821ab927a292d3d21f4"
    assert result["e10d_validation_evidence_commit"] == "06db5defaf1c3c892927089fa2cac18532440298"
    assert result["e10d_final_publication_commit"] == "c173fb77deae4694897bb11ebb3bdbe17baeb940"
    assert result["e10d_authoritative_science_job_source_commit"] == result["e10d_final_publication_commit"]
    assert result["kernel_module_sha256"] == "e19683d6765163cc49cfd4ce1c35d5ddf6835c44ec9a65ab2ec400ad940ac2a6"
    assert result["validation_sha256"] == "8274d1ef6d58581d1f163e90f1fbd4509e2d665de2cdaaa88498b42f050b03e8"
