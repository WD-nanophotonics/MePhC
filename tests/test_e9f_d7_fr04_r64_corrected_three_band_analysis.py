from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = ROOT / "audit/e9f/d7_fr04_r64_corrected_three_band_analysis.py"


def test_normalization_replay_is_exact_and_separates_geometry_quantities():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert '"status": "PASS_EXACT_ACCEPTED_PRODUCTION_REPLAY"' in source
    assert 'BERRY_NORMALIZATION_ID = "E9F_C1_SOURCE_GRID_WILSON_PHASE_OVER_SIGNED_CCW_AREA_V1"' in source
    assert '"fine_offset_h": "1/144"' in source
    assert '"plus_minus_separation": "1/72"' in source
    assert '"actual_oriented_loop_area_q2": "+1/10368"' in source
    assert '"phase_to_public_omega_denominator": "2*(1/144)^2 = 1/10368"' in source
    assert '"reciprocal_space_jacobian_used": False' in source
    assert '"local_stencil_point_order": ["PLUS_X", "PLUS_Y", "MINUS_X", "MINUS_Y"]' in source


def test_d1_bundle_is_exactly_five_axis_points_and_equal_weight():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert 'POINTS = ("PLUS_X", "PLUS_Y", "MINUS_X", "MINUS_Y", "CENTER")' in source
    assert '"PLUS_X": (1, 0)' in source
    assert '"MINUS_X": (-1, 0)' in source
    assert '"PLUS_Y": (0, 1)' in source
    assert '"MINUS_Y": (0, -1)' in source
    assert "RETAINED_CELL_COUNT = 641" in source
    assert "SOURCE_WEIGHT_Q2 = 1.0 / 1296.0" in source


def test_entrypoint_contains_no_new_execution_or_anchor_selection_path():
    source = ENTRYPOINT.read_text(encoding="utf-8")
    assert "provider" in source.lower()  # provenance/forbidden-path assertions remain explicit
    assert "make_provider" not in source
    assert "import meep" not in source
    assert '"native_invocation_count": 0' in source
    assert '"provider_request_count": 0' in source
    assert "solver_executions" not in source
    assert '"anchors_used_for_selection": False' in source
    assert '"anchors_used_for_fitting": False' in source
