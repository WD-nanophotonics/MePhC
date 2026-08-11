"""R1 characterization locks for the current MePhC architecture.

These tests describe the current contract; they do not introduce affine
deformation or modify production/runtime code.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import numpy as np

from mephc.band import Band
from mephc.kspace import (
    SquareKSpace,
    TriangularKSpace,
    square_gxm_path,
    triangular_gkm_path,
)
from mephc.records import make_geometry_id, make_task_key


ROOT = Path(__file__).resolve().parents[1]
TRILATT_ROOT = ROOT.parent / "TriLatt"
SQRLATT_ROOT = ROOT.parent / "SqrLatt"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AffineCharacterizationTests(unittest.TestCase):
  def test_triangular_and_square_direct_basis_are_explicit(self):
    triangular = Band(a=400, r1=100, n_eff=2.7, h=1, resolution=1, lattice_type="triangular")
    square = Band(a=400, r1=100, n_eff=2.7, h=1, resolution=1, lattice_type="square")

    self.assertTrue(np.allclose(
        [triangular.geo_latt.basis1.x, triangular.geo_latt.basis1.y],
        [0.5, np.sqrt(3) / 2],
    ))
    self.assertTrue(np.allclose(
        [triangular.geo_latt.basis2.x, triangular.geo_latt.basis2.y],
        [0.5, -np.sqrt(3) / 2],
    ))
    self.assertTrue(np.allclose([square.geo_latt.basis1.x, square.geo_latt.basis1.y], [1, 0]))
    self.assertTrue(np.allclose([square.geo_latt.basis2.x, square.geo_latt.basis2.y], [0, 1]))


  def test_direct_reciprocal_duality_and_two_pi_convention(self):
    direct = np.column_stack(((0.5, np.sqrt(3) / 2), (0.5, -np.sqrt(3) / 2)))
    reciprocal_without_2pi = np.linalg.inv(direct).T
    self.assertTrue(np.allclose(direct.T @ reciprocal_without_2pi, np.eye(2)))
    self.assertTrue(np.allclose(
        2 * np.pi * reciprocal_without_2pi,
        np.array([[2 * np.pi, 2 * np.pi], [2 * np.pi / np.sqrt(3), -2 * np.pi / np.sqrt(3)]]),
    ))


  def test_first_bz_geometry_and_high_symmetry_paths(self):
    triangular = TriangularKSpace(4)
    vertices = np.asarray(triangular.first_bz_poly)
    area = 0.5 * abs(np.sum(vertices[:, 0] * np.roll(vertices[:, 1], -1) - vertices[:, 1] * np.roll(vertices[:, 0], -1)))
    self.assertTrue(np.isclose(area, 2 * np.sqrt(3) / 3))
    self.assertEqual(square_gxm_path().labels, ("Gamma", "X", "M", "Gamma"))
    self.assertEqual(triangular_gkm_path().labels, ("Gamma", "K", "M", "Gamma"))
    self.assertTrue(np.allclose(square_gxm_path().points[2], (0.5, 0.5)))
    self.assertTrue(np.allclose(triangular_gkm_path().points[1], (2 / 3, 0)))


  def test_square_and_triangular_grid_sampling_contract(self):
    square = np.asarray(SquareKSpace(3).full_grid(extent=1.0))
    triangular = np.asarray(TriangularKSpace(4).full_grid(range_x=(-1, 1), range_y=(-1, 1)))
    self.assertEqual(square.shape, (9, 2))
    self.assertTrue(np.isclose(square[:, 0].min(), -1.0))
    self.assertTrue(np.isclose(square[:, 0].max(), 1.0))
    self.assertEqual(triangular.ndim, 2)
    self.assertEqual(triangular.shape[1], 2)
    self.assertTrue(np.all(triangular[:, 0] >= -1) and np.all(triangular[:, 0] <= 1))
    self.assertTrue(np.all(triangular[:, 1] >= -1) and np.all(triangular[:, 1] <= 1))


  def test_triangular_c3_auto_selection_uses_active_motif(self):
    config = load_module(TRILATT_ROOT / "config.py", "mephc_r1_trilatt_config")
    workflow = load_module(TRILATT_ROOT / "workflow.py", "mephc_r1_trilatt_workflow")
    self.assertTrue(workflow.has_exact_c3_geometry(config))
    self.assertEqual(workflow.resolve_symmetry_mode(config, "auto"), "c3")


  def test_square_case_motif_is_centered_and_geometry_id_is_physical_only(self):
    config = load_module(SQRLATT_ROOT / "square_hole" / "config.py", "mephc_r1_sqrlatt_config")
    pattern = np.asarray(config.build_pattern())
    self.assertEqual(pattern.shape, (4, 2))
    self.assertTrue(np.allclose(pattern.mean(axis=0), (0.0, 0.0)))
    self.assertEqual(config.geometry_id, make_geometry_id("square", "square_hole", a=config.a, d=config.d, n_eff=config.n_eff))
    self.assertNotIn("resolution", config.geometry_id)


  def test_record_identity_excludes_plot_parameters_but_keeps_task_parameters(self):
    task = {"num_bands": 3, "grid_n": 21, "step": 0.01}
    self.assertEqual(make_task_key("bc", task), make_task_key("bc", dict(reversed(list(task.items())))))
    self.assertNotEqual(make_task_key("bc", task), make_task_key("bc", {**task, "grid_n": 22}))
    self.assertNotEqual(make_task_key("bc", task), make_task_key("band", task))


  def test_one_low_resolution_solver_smoke(self):
    try:
      import meep  # noqa: F401
    except ImportError:
      self.skipTest("meep is unavailable")
    band = Band(a=400, r1=100, n_eff=2.7, h=1, resolution=2, lattice_type="square")
    freqs = band.run_simulation_te({(0.0, 0.0): 0.2}, [band.Gamma], num_b=1)
    self.assertGreaterEqual(np.asarray(freqs).size, 1)


if __name__ == "__main__":
  unittest.main()
