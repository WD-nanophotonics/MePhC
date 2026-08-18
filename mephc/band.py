from __future__ import annotations

import math
from dataclasses import dataclass

import meep as mp
from matplotlib import pyplot as plt
from meep import mpb
import numpy as np

from . import lattice as ml
from .berry import BerryCurvatureCalculator
from .bravais import BravaisLattice2D
from .bz import first_brillouin_zone
from .efs import EFSResult, plot_efs
from .geometry import to_meep_geometry
from .kspace import (
    HighSymmetryPath,
    TriangularKSpace,
    square_full_zone_points,
    square_gxm_path,
    triangular_gkm_path,
    triangular_reduced_zone_points,
    generic_bz_path,
)
from .plotting import plot_band_path, plot_scalar_field
from .capabilities import field_capabilities, require_primitive, require_supercell
from .deformation import canonicalize_field


@dataclass(frozen=True)
class SupercellGeometryContext:
    """Verified geometry artifacts shared by R6 consumers."""

    field: object
    replication: tuple[int, int]
    geometry_lattice: object
    feature_geometry: list
    geometry: list


class Band:
    """Shared 2D MPB interface for triangular and square photonic lattices.

    Physical lengths ``a``, ``r1``, ``r2``, and ``h`` must use one consistent
    unit; frequency conversion assumes ``a`` is in nm. Geometry patterns and
    public k-points use normalized real-space and Cartesian reciprocal-space
    coordinates, respectively.
    """

    def __init__(
        self,
        a=400,
        r1=120,
        r2=80,
        n_eff=2.7,
        h=1000,
        resolution=128,
        lattice_type="triangular",
        polarization="TE",
        structure_type="slab",
        lattice_model=None,
        deformation_field=None,
    ):
        self.a = a
        self.r1 = r1
        self.r2 = r2
        self.n_eff = n_eff
        self.h = h
        self.resolution = resolution
        self.lattice_type = self._normalize_lattice_type(lattice_type)
        self.polarization = self._normalize_polarization(polarization)
        self.structure_type = self._normalize_structure_type(structure_type)
        self.lattice_model = lattice_model or BravaisLattice2D.named(self.lattice_type)
        self.deformation_field = canonicalize_field(deformation_field)
        if self.lattice_model.kind in {"triangular", "square"}:
            self.lattice_type = self.lattice_model.kind
        self.mpb_parity = mp.TE if self.polarization == "TE" else mp.TM
        self.Si = mp.Medium(epsilon=n_eff**2)
        self.geo_latt = self.lattice_model.to_meep_lattice(size=(1.0, 1.0))
        self.Gamma = mp.Vector3()
        if self.lattice_type == "square":
            self.X = mp.Vector3(0.5, 0.0)
            self.M = mp.Vector3(0.5, 0.5)
            self.K = self.M
        else:
            self.M = mp.Vector3(y=0.5)
            self.K = mp.Vector3(1 / 3, 1 / 3)

    @staticmethod
    def _normalize_lattice_type(lattice_type: str) -> str:
        aliases = {
            "triangular": "triangular",
            "tri": "triangular",
            "t": "triangular",
            "honeycomb": "triangular",
            "hon": "triangular",
            "hc": "triangular",
            "h": "triangular",
            "square": "square",
            "sqr": "square",
            "s": "square",
        }
        key = str(lattice_type).lower()
        if key not in aliases:
            raise ValueError("lattice_type must be 'triangular' or 'square'.")
        return aliases[key]

    @staticmethod
    def _normalize_polarization(polarization: str) -> str:
        value = str(polarization).strip().upper()
        if value not in {"TE", "TM"}:
            raise ValueError("polarization must be 'TE' or 'TM'.")
        return value

    @staticmethod
    def _normalize_structure_type(structure_type: str) -> str:
        value = str(structure_type).strip().lower()
        if value not in {"slab", "pillar"}:
            raise ValueError("structure_type must be 'slab' or 'pillar'.")
        return value

    @staticmethod
    def _make_geometry_lattice(lattice_type: str):
        """Compatibility factory delegating named bases to the kernel."""

        return BravaisLattice2D.named(lattice_type).to_meep_lattice(size=(1.0, 1.0))

    def first_bz(self):
        """Return the generic Wigner-Seitz first BZ for this lattice model."""

        self.require_primitive_semantics("first Brillouin-zone construction")
        return first_brillouin_zone(self.lattice_model)

    def require_primitive_semantics(self, operation: str):
        return require_primitive(self.deformation_field, operation)

    def deformation_capabilities(self) -> dict[str, object]:
        return field_capabilities(self.deformation_field)


    def default_path(self) -> HighSymmetryPath:
        """Return an identity path or honest generic BZ landmark path."""
        self.require_primitive_semantics("primitive high-symmetry path")
        if self.lattice_type == "square":
            return square_gxm_path() if self.lattice_model.is_identity else generic_bz_path(self.lattice_model)
        if self.lattice_model.supports_legacy("gkm"):
            return triangular_gkm_path()
        return generic_bz_path(self.lattice_model)

    def create_material_block(self):
        """Return the dielectric background for a slab, or no block for pillars."""
        if self.structure_type == "pillar":
            return []
        return [mp.Block(material=self.Si, size=mp.Vector3(mp.inf, mp.inf, self.h))]

    @property
    def feature_material(self):
        """Return air for slab holes and dielectric for pillars."""
        return mp.air if self.structure_type == "slab" else self.Si

    def convert_ndarray_to_meep_geo(self, pattern, material=None, rectify=True, cylinder=0):
        """Convert normalized pattern data into Meep geometry objects.

        ``rectify`` maps vertices through the geometry lattice before MPB use.
        ``cylinder`` is retained for compatibility: a truthy value forces
        cylinders; otherwise shape detection is automatic. When ``material``
        is omitted, slab patterns are air holes and pillar patterns are
        dielectric inclusions.
        """
        if material is None:
            material = self.feature_material
        shape = "cylinder" if cylinder else "auto"
        return to_meep_geometry(
            pattern,
            material=material,
            height=self.h,
            geometry_lattice=self.geo_latt,
            rectify=rectify,
            shape=shape,
        )

    def _prepare_supercell_geometry(self, pattern, field):
        """Prepare the sole verified R6 geometry/context authority."""
        field = canonicalize_field(field)
        require_supercell(field, "periodic-supercell geometry")
        replication_matrix = np.asarray(field.supercell.matrix, dtype=int)
        if not np.array_equal(replication_matrix, np.diag(np.diag(replication_matrix))):
            raise ValueError("R6 supercell solver currently requires diagonal replication")
        replication = tuple(int(value) for value in np.diag(replication_matrix))
        geometry_lattice = field.supercell.reference_lattice.to_meep_lattice(size=replication)
        feature_geometry = to_meep_geometry(
            pattern,
            material=self.feature_material,
            height=self.h,
            geometry_lattice=geometry_lattice,
            rectify=True,
            shape="auto",
        )
        geometry = self.create_material_block() + feature_geometry
        return SupercellGeometryContext(
            field=field,
            replication=replication,
            geometry_lattice=geometry_lattice,
            feature_geometry=feature_geometry,
            geometry=geometry,
        )

    def build_supercell_solver(self, pattern, field, *, q_points, num_bands, resolution=None):
        """Build a periodic-supercell MPB solver from explicit R6 inputs."""
        context = self._prepare_supercell_geometry(pattern, field)
        vectors = []
        for point in q_points:
            point_id = getattr(point, "point_id", None)
            if point_id in {"Gamma", "K", "M", "X"}:
                raise ValueError("R6 supercell q-point IDs must remain generic")
            fractional = getattr(point, "fractional", point)
            values = np.asarray(fractional, dtype=float)
            if values.shape != (2,) or not np.all(np.isfinite(values)):
                raise ValueError("supercell q-points must be finite 2D fractional coordinates")
            vectors.append(mp.Vector3(float(values[0]), float(values[1])))
        return mpb.ModeSolver(
            geometry_lattice=context.geometry_lattice,
            geometry=context.geometry,
            default_material=mp.air,
            resolution=self.resolution if resolution is None else int(resolution),
            num_bands=int(num_bands),
            k_points=vectors,
            verbose=False,
        )

    def build_supercell_berry_calculator(
        self,
        pattern,
        field,
        *,
        num_bands,
        resolution=None,
        overlap_tol=1e-14,
        run_band_func=mpb.fix_efield_phase,
        polarization=None,
        eigensolver_tolerance=1e-7,
        deterministic=False,
        overlap_formulation="energy_eh",
    ):
        """Configure BerryCurvatureCalculator with the verified R6 geometry."""
        context = self._prepare_supercell_geometry(pattern, field)
        normalized = self._normalize_polarization(
            self.polarization if polarization is None else polarization
        )
        return BerryCurvatureCalculator(
            geometry=context.geometry,
            geometry_lattice=context.geometry_lattice,
            resolution=self.resolution if resolution is None else int(resolution),
            num_bands=int(num_bands),
            polarization=mp.TE if normalized == "TE" else mp.TM,
            run_band_func=run_band_func,
            default_material=mp.air,
            verbose=False,
            overlap_tol=overlap_tol,
            eigensolver_tolerance=eigensolver_tolerance,
            deterministic=deterministic,
            overlap_formulation=overlap_formulation,
        )

    def run_supercell(self, pattern, field, *, q_points, num_bands, resolution=None, polarization=None):
        """Run the verified periodic-supercell solver and return its raw solver."""
        solver = self.build_supercell_solver(
            pattern,
            field,
            q_points=q_points,
            num_bands=num_bands,
            resolution=resolution,
        )
        normalized = self._normalize_polarization(self.polarization if polarization is None else polarization)
        solver.run_parity(p=mp.TE if normalized == "TE" else mp.TM, reset_fields=True)
        return solver
    def run_simulation(self, pattern, ks, num_b, show_dielectric=False, polarization=None):
        """Run the configured TE/TM parity, optionally overriding it per call."""
        self.require_primitive_semantics("primitive MPB band solve")
        if polarization is None:
            parity = self.mpb_parity
        else:
            normalized = self._normalize_polarization(polarization)
            parity = mp.TE if normalized == "TE" else mp.TM
        shape = self.convert_ndarray_to_meep_geo(pattern, rectify=True)
        ms = mpb.ModeSolver(
            geometry_lattice=self.geo_latt,
            geometry=self.create_material_block() + shape,
            default_material=mp.air,
            resolution=self.resolution,
            num_bands=num_b,
            k_points=ks,
            verbose=False,
        )
        ms.run_parity(p=parity, reset_fields=True)

        if show_dielectric:
            dis = ms.get_epsilon()
            plt.imshow(dis.T, interpolation="spline36", cmap="binary")
            plt.axis("off")
            plt.show()

            md = mpb.MPBData(rectify=True, resolution=64, periods=3)
            rectangular_data = md.convert(dis)
            plt.imshow(rectangular_data.T, interpolation="spline36", cmap="binary")
            plt.axis("off")
            plt.show()

        return ms.freqs

    def run_simulation_te(self, pattern, ks, num_b, show_dielectric=False):
        """Backward-compatible TE-only wrapper around :meth:`run_simulation`."""
        return self.run_simulation(
            pattern,
            ks,
            num_b,
            show_dielectric=show_dielectric,
            polarization="TE",
        )

    def calculate_actual_freqs(self, fs):
        """Convert normalized MPB frequencies to THz using lattice constant ``a``."""
        array = np.asarray(fs)
        result = array * 299792.458 / self.a
        if np.isscalar(fs):
            return float(result)
        return result.tolist()

    def create_unitcell(self, n1, theta1, n2=None, theta2=None, show=True):
        if self.lattice_type == "square":
            lattice = ml.Lattice(
                period=1,
                outline=[(-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)],
                orientation=0,
                lattice_type="square",
                lattice_model=self.lattice_model,
            )
        elif self.r2 is None:
            lattice = ml.Lattice(period=1, outline=[(-0.1, 0.6), (1, 0.6), (1, 0), (-0.1, 0)], orientation=0, lattice_type="t", lattice_model=self.lattice_model)
        else:
            lattice = ml.Lattice(period=1, outline=[(-0.1, 0.6), (1, 0.6), (1, 0), (-0.1, 0)], orientation=0, lattice_type="hc", lattice_model=self.lattice_model)

        if show:
            lattice.preview_lattice(show_outline=True)

        if n2:
            pc = lattice.PolygonPattern(n1, self.r1 / self.a, theta1, n2, self.r2 / self.a, theta2)
        else:
            pc = lattice.PolygonPattern(n1, self.r1 / self.a, theta1)

        if show:
            pc.preview_pattern()

        return pc

    def get_three_bands_at_K(self, pattern, show=False):
        freqs = self.run_simulation(pattern, [self.K], 3, show_dielectric=show)
        return self.calculate_actual_freqs(freqs)

    def berry_calculator(self, num_bands=None, geometry=None):
        """Build a Berry calculator using this lattice, material, and resolution."""
        self.require_primitive_semantics("primitive Berry solver")
        if num_bands is None:
            num_bands = 3
        feature_geometry = [] if geometry is None else list(geometry)
        return BerryCurvatureCalculator(
            geometry=self.create_material_block() + feature_geometry,
            geometry_lattice=self.geo_latt,
            resolution=self.resolution,
            num_bands=num_bands,
            polarization=self.mpb_parity,
            run_band_func=mpb.fix_efield_phase,
            default_material=mp.air,
            verbose=False,
        )

    def calculate_berry_curvature(self, pattern, k_point, step, num_bands, band_index=None):
        """Calculate one plaquette at a Cartesian k-point.

        ``step`` uses the same reciprocal-coordinate units as ``k_point``.
        ``band_index`` is 0-based; ``None`` returns all requested bands.
        """
        geometry = self.convert_ndarray_to_meep_geo(pattern, rectify=True)
        calculator = self.berry_calculator(num_bands=num_bands, geometry=geometry)
        return calculator.calculate(k_point, step=step, band_index=band_index)

    def compute_berry_grid(self, pattern, k_points, step, num_bands, band_index=None, symmetry=None):
        """Calculate Berry curvature at arbitrary ``(N, 2)`` Cartesian k-points.

        Returns ``bcs`` with shape ``(N, num_bands)`` when ``band_index=None``,
        or ``(N,)`` for one 0-based band.
        """
        k_points = np.asarray(k_points, dtype=float)
        self.require_primitive_semantics("primitive Berry sampling")
        if k_points.ndim != 2 or k_points.shape[1] != 2:
            raise ValueError("k_points must have shape (N, 2).")
        if band_index is not None and (band_index < 0 or band_index >= num_bands):
            raise ValueError(f"band_index must be between 0 and {num_bands - 1}")
        if symmetry == "c3" and not self.lattice_model.supports_legacy("c3"):
            raise ValueError("C3 Berry sampling is unavailable for a non-identity lattice")

        geometry = self.convert_ndarray_to_meep_geo(pattern, rectify=True)
        calculator = self.berry_calculator(num_bands=num_bands, geometry=geometry)
        if band_index is None:
            values = np.zeros((len(k_points), num_bands), dtype=float)
        else:
            values = np.zeros(len(k_points), dtype=float)

        for idx, k_point in enumerate(k_points):
            values[idx] = calculator.calculate(k_point, step=step, band_index=band_index)

        return {
            "k_points": k_points,
            "bcs": values,
            "step": float(step),
            "num_bands": int(num_bands),
            "band_index": band_index,
            "lattice_type": self.lattice_type,
            "polarization": self.polarization,
            "structure_type": self.structure_type,
            "k_coordinate": "cartesian_reciprocal",
            "symmetry": symmetry or "none",
            "lattice": self.lattice_model.metadata(),
        }

    def _run_cartesian_k_frequencies(self, geometry, k_point, num_bands):
        reciprocal_k = mp.cartesian_to_reciprocal(mp.Vector3(float(k_point[0]), float(k_point[1]), 0), self.geo_latt)
        ms = mpb.ModeSolver(
            geometry_lattice=self.geo_latt,
            geometry=geometry,
            default_material=mp.air,
            resolution=self.resolution,
            num_bands=num_bands,
            k_points=[reciprocal_k],
            verbose=False,
        )
        ms.run_parity(self.mpb_parity, False, mpb.fix_efield_phase)
        return np.asarray(ms.freqs[:num_bands], dtype=float)

    def compute_band_path_with_berry(
        self,
        pattern,
        path: HighSymmetryPath | None = None,
        n_per_segment: int = 10,
        step: float = 0.0005,
        num_bands: int = 3,
        compute_bc: bool = True,
    ):
        """Calculate frequencies and optional Berry color data along a path.

        ``n_per_segment`` is intervals per path segment. ``compute_bc=False``
        skips all field/plaquette work and returns ``bcs=None``. At exact
        high-symmetry vertices, only the Berry plaquette anchor is offset;
        frequency remains evaluated at the original path point.
        """
        self.require_primitive_semantics("primitive band/Berry path")
        if path is None:
            path = self.default_path()

        k_points, distances, tick_indices, tick_positions = path.interpolate(n_per_segment=n_per_segment)
        feature_geometry = self.convert_ndarray_to_meep_geo(pattern, rectify=True)
        geometry = self.create_material_block() + feature_geometry
        freqs = np.zeros((len(k_points), num_bands), dtype=float)
        bcs = np.zeros_like(freqs) if compute_bc else None
        calculator = self.berry_calculator(num_bands=num_bands, geometry=feature_geometry) if compute_bc else None

        for idx, k_point in enumerate(k_points):
            freqs[idx] = self._run_cartesian_k_frequencies(geometry, k_point, num_bands)
            if compute_bc:
                bc_anchor = path.offset_high_symmetry_point(k_point, step=step)
                bcs[idx] = np.asarray(calculator.calculate(bc_anchor, step=step), dtype=float)

        return {
            "k_points": k_points,
            "distances": distances,
            "tick_indices": tick_indices,
            "tick_positions": tick_positions,
            "labels": path.labels,
            "freqs": freqs,
            "actual_freqs": np.asarray(self.calculate_actual_freqs(freqs), dtype=float),
            "bcs": bcs,
            "step": float(step),
            "n_per_segment": int(n_per_segment),
            "lattice_type": self.lattice_type,
            "polarization": self.polarization,
            "structure_type": self.structure_type,
            "lattice": self.lattice_model.metadata(),
            "path_coordinate": "cartesian_reciprocal",
        }

    def compute_efs(self, pattern, k_points, num_bands=3):
        """Calculate normalized and THz frequencies at arbitrary k-points."""
        k_points = np.asarray(k_points, dtype=float)
        self.require_primitive_semantics("primitive EFS sampling")
        if k_points.ndim != 2 or k_points.shape[1] != 2:
            raise ValueError("k_points must have shape (N, 2).")
        feature_geometry = self.convert_ndarray_to_meep_geo(pattern, rectify=True)
        geometry = self.create_material_block() + feature_geometry
        freqs = np.zeros((len(k_points), num_bands), dtype=float)
        for idx, k_point in enumerate(k_points):
            freqs[idx] = self._run_cartesian_k_frequencies(geometry, k_point, num_bands)
        return EFSResult(
            k_points=k_points,
            freqs=freqs,
            actual_freqs=np.asarray(self.calculate_actual_freqs(freqs), dtype=float),
            metadata={
                "a": self.a,
                "resolution": self.resolution,
                "num_bands": num_bands,
                "k_coordinate": "cartesian_reciprocal",
                "lattice_type": self.lattice_type,
                "polarization": self.polarization,
                "structure_type": self.structure_type,
                "lattice": self.lattice_model.metadata(),
            },
        )

    def compute_triangular_efs(self, pattern, N, shrinking=0.01, num_bands=3):
        """Calculate EFS data on identity C3 space or the current full BZ."""
        kspace = TriangularKSpace(N=N, shrinking=shrinking, lattice_model=self.lattice_model)
        if self.lattice_model.supports_legacy("mini_space"):
            k_points = np.asarray(kspace.mini_space(), dtype=float)
            grid_name = "triangular_reduced_zone"
        else:
            k_points = np.asarray(kspace.full_bz(), dtype=float)
            grid_name = "current_first_bz"
        if len(k_points) == 0:
            raise ValueError("the selected reciprocal domain contains no k-points")
        result = self.compute_efs(pattern, k_points, num_bands=num_bands)
        result.metadata.update({"grid": grid_name, "N": N, "shrinking": shrinking, "symmetry": "c3" if self.lattice_model.is_identity else "none"})
        return result

    def compute_square_efs(self, pattern, N, extent=0.5, num_bands=3):
        """Calculate identity square-grid or current-BZ EFS data.

        The legacy square grid and ordering are retained only for the identity
        square lattice. An affine square lattice dispatches to its validated
        current Wigner-Seitz BZ through the canonical lattice model.
        """
        if self.lattice_model.is_identity:
            k_points = np.asarray(square_full_zone_points(N=N, extent=extent), dtype=float)
            grid_name = "square_full_zone"
        else:
            k_points = np.asarray(
                SquareKSpace(N=N, lattice_model=self.lattice_model).current_bz(),
                dtype=float,
            )
            grid_name = "current_first_bz"
        result = self.compute_efs(pattern, k_points, num_bands=num_bands)
        result.metadata.update({"grid": grid_name, "N": N, "extent": extent, "domain": grid_name})
        return result

    def plot_efs(self, result: EFSResult, band_index=0, **kwargs):
        return plot_efs(result, band_index=band_index, **kwargs)

    def plot_band_path(self, result: dict, **kwargs):
        return plot_band_path(result, **kwargs)

    def plot_berry_grid(self, result: dict, band_index=0, **kwargs):
        """Plot one 0-based band from a Berry-grid result."""
        bcs = np.asarray(result["bcs"], dtype=float)
        if bcs.ndim == 2:
            if band_index < 0 or band_index >= bcs.shape[1]:
                raise ValueError(f"band_index must be between 0 and {bcs.shape[1] - 1}")
            values = bcs[:, band_index]
        else:
            values = bcs
        title = kwargs.pop("title", f"Berry curvature (Band {band_index + 1})")
        return plot_scalar_field(
            result["k_points"],
            values,
            title=title,
            colorbar_label="Berry curvature",
            **kwargs,
        )
