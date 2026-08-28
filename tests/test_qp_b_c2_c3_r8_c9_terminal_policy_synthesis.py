from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "audit/e9f/qp_b_c2_c3_r8_c9_terminal_policy_synthesis.py"


def load():
    spec = importlib.util.spec_from_file_location("r8_c9_synthesis", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_c8_evidence_and_c1_anchors_are_exact() -> None:
    module = load()
    c8 = module.validate_c8_evidence()
    c1 = module.accepted_c1_source_reproduction()
    assert c8["even_subsequence_stencil_pass_count"] == 4
    assert c8["total_terminal_fixed_h_pass_count"] == 6
    assert c1["band0_valley_chern"] == -0.09405797052154485
    assert c1["band1_valley_chern"] == 0.5086915675292921
    assert c1["band2_numeric_chern"] is None


def test_terminal_policy_synthesis_is_conservative_and_solver_free() -> None:
    module = load()
    result = module.synthesize()
    assert result["analysis_mode"] == "ARTIFACT_ONLY_ANALYSIS"
    assert result["current_0p02_production_policy_action"] == "RETAIN_UNCHANGED"
    assert result["global_threshold_relaxation_supported"] is False
    assert result["below_policy_noninferior_count"] == 1
    assert result["below_policy_inferior_count"] == 4
    assert result["below_policy_incomplete_count"] == 0
    assert result["source_reproduction"]["band2_numeric_chern"] is None
    assert result["execution"] == {
        "native_invocation_count": 0, "provider_request_count": 0,
        "native_solves": 0, "mpb_execution": False,
    }
    assert result["terminal"].endswith("TERMINAL_POLICY_SYNTHESIS_COMPLETE")


def test_band2_endpoint_preserves_forbidden_substitutes() -> None:
    module = load()
    endpoint = module.band2_endpoint(module.synthesize())
    assert endpoint["endpoint"] == "SOURCE_BOUND_BAND2_CLOSE_INCOMPLETE_UNDER_CURRENT_CONTRACT"
    assert endpoint["numeric_chern"] is None
    assert endpoint["reducer_executed"] is False
    assert endpoint["rank2_substitute_used"] is False
    assert "zero-fill" in endpoint["forbidden_substitutes"]
    assert "interpolation" in endpoint["forbidden_substitutes"]


def test_source_has_no_execution_or_threshold_change_path() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "import meep" not in source
    assert "subprocess" not in source
    assert "provider_solve" not in source
    assert "threshold_change_authorized = True" not in source
