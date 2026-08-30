from __future__ import annotations

import importlib.util
import py_compile
from dataclasses import dataclass
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "audit" / "local_affine" / "third_scale_6_state_tight_eigensolver_live_acquisition.py"


def _module():
    spec = importlib.util.spec_from_file_location("p96_acquisition", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@dataclass(frozen=True)
class _StateDouble:
    model_id: str
    reference_cell_id: str
    q: tuple[float, float]
    s: float
    F_s: tuple[tuple[float, float], tuple[float, float]]
    A_s: tuple[tuple[float, float], tuple[float, float]]
    derived_kappa: tuple[float, float]
    geometry_digest: str
    geometry: tuple[str, ...]
    geometry_lattice: tuple[str, ...]
    eigensolver_tolerance: float = 1e-7
    resolution: int = 64
    num_bands: int = 6
    polarization: str = "TM"
    mesh_size: int = 3
    deterministic: bool = True
    h_representation: str = "mpb_periodic_h_l2_v1"
    bloch_phase_excluded: bool = True
    component_basis: str = "LAB_CARTESIAN"
    mu_contract: str = "MU1_NONMAGNETIC"
    orientation_sign: int = 1
    fractional_material_indexing_identity: str = "SAME_FRACTIONAL_IX_IY_MATERIAL_COORDINATES"
    reference_cell_identity: str = "E8B_TWO_INCLUSION_REFERENCE_FRACTIONAL_CELL_V1"
    bloch_phase_convention: str = "EXCLUDED_PERIODIC_H_ENVELOPE"

    @property
    def public_q(self):
        return self.q


def _install_state_double(monkeypatch, module):
    def fake_make_state(public_q, s):
        q = tuple(float(value) for value in public_q)
        return _StateDouble(
            model_id="E8B_TWO_INCLUSION_AREA_PRESERVING_AFFINE_V1",
            reference_cell_id="E8B_TWO_INCLUSION_REFERENCE_FRACTIONAL_CELL_V1",
            q=q,
            s=float(s),
            F_s=((1.0, 0.0), (0.0, 1.0)),
            A_s=((0.8660254037844386, 0.8660254037844386), (0.5, -0.5)),
            derived_kappa=(q[0], q[1]),
            geometry_digest="geometry-digest",
            geometry=("geometry",),
            geometry_lattice=("lattice",),
        )

    monkeypatch.setattr(module, "make_state", fake_make_state)


def test_all_six_tight_specs_have_exact_coordinates_and_state_side_tolerance(monkeypatch):
    module = _module()
    _install_state_double(monkeypatch, module)
    graph, _ = module.load_graph({})
    for item in graph["states"]:
        baseline = module.make_state(tuple(item["public_q"]), float(item["s"]))
        tight = module.make_tight_state(item["public_q"], item["s"])
        assert tight.public_q == baseline.public_q == tuple(item["public_q"])
        assert tight.s == baseline.s == float(item["s"])
        assert tight.geometry == baseline.geometry
        assert tight.geometry_lattice == baseline.geometry_lattice
        assert tight.geometry_digest == baseline.geometry_digest
        assert tight.eigensolver_tolerance == 1e-9
        assert module.canonical_tight_state_identity(tight)["eigensolver_tolerance"] == 1e-9


def test_unadjusted_state_rejects_tight_provider_contract_but_corrected_state_aligns(monkeypatch):
    module = _module()
    _install_state_double(monkeypatch, module)
    baseline = module.make_state((0.00025, -0.6166666666666667), 0.0)
    with pytest.raises(Exception, match="LOCAL_AFFINE_STATE_CONTRACT_MISMATCH:eigensolver_tolerance"):
        module.canonical_tight_state_identity(baseline)
    tight = module.make_tight_state((0.00025, -0.6166666666666667), 0.0)
    identity = module.canonical_tight_state_identity(tight)
    assert identity["eigensolver_tolerance"] == 1e-9


def test_only_solver_contract_tolerance_differs_from_baseline_identity(monkeypatch):
    module = _module()
    _install_state_double(monkeypatch, module)
    baseline = module.make_state((0.0, -0.6166666666666667), 0.0)
    tight = module.make_tight_state((0.0, -0.6166666666666667), 0.0)
    baseline_identity = module.canonical_state_identity(baseline)
    tight_identity = module.canonical_tight_state_identity(tight)
    assert baseline_identity["eigensolver_tolerance"] == 1e-7
    assert tight_identity["eigensolver_tolerance"] == 1e-9
    comparable = set(baseline_identity) - {"eigensolver_tolerance"}
    assert {key: baseline_identity[key] for key in comparable} == {key: tight_identity[key] for key in comparable}


def test_tight_state_is_an_immutable_replacement_not_in_place_mutation(monkeypatch):
    module = _module()
    _install_state_double(monkeypatch, module)
    baseline = module.make_state((0.0, -0.6166666666666667), 0.0)
    tight = module.make_tight_state((0.0, -0.6166666666666667), 0.0)
    assert tight is not baseline
    assert baseline.eigensolver_tolerance == 1e-7
    assert tight.eigensolver_tolerance == 1e-9


def test_entrypoint_compiles_and_does_not_bypass_provider_validation():
    module = _module()
    assert module is not None
    py_compile.compile(str(TARGET), doraise=True)
    source = TARGET.read_text(encoding="utf-8")
    assert "replace(base, eigensolver_tolerance=SOLVER_CONFIGURATION[\"eigensolver_tolerance\"])" in source
    assert "monkeypatch" not in source
    assert "LocalAffineStateProvider" in source
    assert "eigensolver_tolerance=1e-9" in source
    assert "archived runtime" not in source.lower()
