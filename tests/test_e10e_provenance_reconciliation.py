from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "audit/e10e/e10e_provenance_reconciliation.py"


def load_module():
    spec = importlib.util.spec_from_file_location("e10e_provenance_reconciliation", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_reconciliation_identifies_the_single_e10e_publication_commit():
    module = load_module()
    result = module.build_reconciliation()

    assert result["e10e_kernel_implementation_commit"] == "3a5b41d3e38e3d61a993886de802b197a5d75a89"
    assert result["e10e_validation_evidence_commit"] == result["e10e_kernel_implementation_commit"]
    assert result["e10e_final_publication_commit"] == result["e10e_kernel_implementation_commit"]
    assert result["e10e_authoritative_science_job_source_commit"] == result["e10e_final_publication_commit"]
    assert result["commit_lineage_status"] == "PASS"
    assert result["authoritative_science_source_status"] == "PASS"


def test_reconciliation_preserves_kernel_and_validation_without_execution():
    module = load_module()
    result = module.build_reconciliation()

    assert result["embedded_final_origin_status"] == "NONAUTHORITATIVE_BASE_BOUND"
    assert result["downstream_provenance_binding_status"] == "PASS"
    assert result["e10e_scientific_kernel_status"] == "ACCEPTED"
    assert result["e10e_provenance_reconciliation_status"] == "PASS"
    assert result["e10e_ready_for_e10f"] is True
    assert result["kernel_bytes_unchanged"] is True
    assert result["validation_bytes_unchanged"] is True
    assert result["native_invocation_count"] == 0
    assert result["provider_executions"] == 0
    assert result["solver_executions"] == 0
    assert result["mpb_execution"] is False
