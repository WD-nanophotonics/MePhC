from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "audit/berry_c3_consistency/m64r4_exact_build5_isolated_localize_patch_ab.py"
SPEC = importlib.util.spec_from_file_location("m64r4", SOURCE)
assert SPEC and SPEC.loader
m64r4 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m64r4)


def test_exact_source_recipe_driver_and_prior_probe_accounting_are_bound():
    assert m64r4.SOURCE_SHA == "8d2b206254b217f66a53c1ad20cc0c369b93b0e71ee671d68e333a583eaaeda4"
    assert len(m64r4.DRIVER_SHA) == 64 and m64r4.M64R3[3] == 4


def test_analytic_reference_is_independent_and_four_band():
    values = m64r4._analytic([0.123456, -0.210987])
    assert len(values) == 4 and values == sorted(values)


def test_isolated_probe_consumes_before_child_call_and_never_applies_patch():
    text = SOURCE.read_text(encoding="utf-8")
    assert "counter.consume_solver()" in text
    assert '"patch_applied": False' in text
    assert "subprocess.run" in text and "build_exact_build5.sh" in text


def test_no_installed_backend_mutation_or_old_probe_rerun_is_encoded():
    text = SOURCE.read_text(encoding="utf-8")
    assert "installed_backend_touched" in text and "prior_completed_solver_probes" in text
    assert "M64R3" in text and "M64R2" not in text
