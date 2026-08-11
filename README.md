# MePhC

MePhC is a reusable Python package for building photonic-crystal geometry and running small Meep/MPB workflows. The package currently focuses on:

- lattice and polygon pattern construction
- NumPy/pattern to Meep geometry conversion
- MPB band-structure helpers
- MPB plaquette Berry curvature helpers
- equi-frequency surface/contour helpers
- high-symmetry k-path generation

The working Python environment used for development is:

```bash
/home/icy/miniconda3/envs/mp/bin/python
```

That environment provides Meep/MPB and the scientific Python libraries used by this package.

## Use From Another Directory

Recommended for local development:

```bash
PYTHONPATH=/home/icy/MePhC /home/icy/miniconda3/envs/mp/bin/python your_script.py
```

If the environment has `pip`, an editable install is also appropriate:

```bash
/home/icy/miniconda3/envs/mp/bin/python -m pip install -e /home/icy/MePhC
```

For another project using the public release:

```bash
python -m pip install \\
  "mephc @ git+https://github.com/WD-nanophotonics/MePhC.git@v0.1.1"
```

## Imports

Use package imports in new code:

```python
from mephc.lattice import Lattice
from mephc.geometry import to_meep_geometry
from mephc.band import Band
from mephc.berry import BerryCurvatureCalculator
from mephc.efs import EFSInterpolator, EFSResult, plot_efs
from mephc.kspace import (
    SquareKSpace,
    TriangularKSpace,
    triangular_gkm_path,
    square_gxm_path,
)
from mephc.workflows import resolve_record, save_record_outputs
```

## Minimal Examples

Build a lattice pattern:

```python
from mephc.lattice import Lattice
from mephc.patterns import pattern_summary

lattice = Lattice(
    period=1,
    outline=[(-0.1, 0.6), (1, 0.6), (1, 0), (-0.1, 0)],
    orientation=0,
    lattice_type="hc",
)
pattern = lattice.PolygonPattern(3, 0.25, 30, 3, 0.18, 0)
print(pattern_summary(pattern))
```

Run a small band calculation:

```python
from mephc.band import Band

band = Band(a=400, r1=90, r2=None, n_eff=2.7, h=1, resolution=16)
pattern = band.create_unitcell(3, 30, show=False)
freqs = band.run_simulation_te(pattern, [band.K], num_b=2)
print(freqs)
```

Compute Berry curvature near K:

```python
from mephc.band import Band

band = Band(a=400, r1=90, r2=None, n_eff=2.7, h=1, resolution=12)
pattern = band.create_unitcell(3, 30, show=False)
values = band.calculate_berry_curvature(
    pattern=pattern,
    k_point=(2.0 / 3.0 + 0.01, 0.01),
    step=0.01,
    num_bands=2,
)
print(values)
```

Compute and plot an EFS contour:

```python
from mephc.band import Band
from mephc.kspace import triangular_full_grid_points

band = Band(a=400, r1=90, r2=None, n_eff=2.7, h=1, resolution=8)
pattern = band.create_unitcell(3, 30, show=False)
k_points = triangular_full_grid_points(N=2, range_x=(0.0, 0.8), range_y=(-0.35, 0.35))
result = band.compute_efs(pattern, k_points=k_points, num_bands=2)
fig, ax = band.plot_efs(result, band_index=0, use_actual=True, mesh_size=40, interpolation="linear")
```


Run a square-lattice band path and Berry/EFS workflows:

```python
from mephc.band import Band
from mephc.kspace import square_full_zone_points, square_gxm_path

band = Band(a=400, n_eff=2.7, h=1, resolution=8, lattice_type="square")
pattern = {(0.0, 0.0): 0.22}
path_data = band.compute_band_path_with_berry(
    pattern,
    path=square_gxm_path(),
    n_per_segment=2,
    num_bands=2,
    compute_bc=False,
)
fig, ax = band.plot_band_path(path_data, show=False)

k_points = square_full_zone_points(N=3)
berry = band.compute_berry_grid(pattern, k_points, step=0.02, num_bands=2, band_index=0)
fig, ax = band.plot_berry_grid(berry, show=False)

efs = band.compute_square_efs(pattern, N=3, num_bands=2)
fig, ax = band.plot_efs(efs, band_index=0, interpolation="linear", show=False)
```

Shared case projects can use `mephc.workflows` to resolve an explicit,
reusable, or plot-only record and to write canonical, archive, and temporary
outputs without duplicating the record bookkeeping.

## Data And Archive Policy

MePhC contains reusable code only. Project-specific `.pkl` records, generated
images, MPB caches, and temporary outputs belong to the consuming project and
are kept out of Git. Those projects may track a small `archive_manifest.json`
containing record names, task parameters, compute parameters, timestamps, and
hashes without publishing the binary records.

## Click-Run Examples

The `examples/` directory contains small VS Code runnable scripts:

- `01_build_lattice.py`
- `02_convert_geometry.py`
- `03_band_at_k.py`
- `04_berry_curvature_at_k.py`
- `05_band_path_with_berry.py`
- `06_efs_contour.py`

They are intentionally small and use low resolutions so the environment can be checked quickly.

## Legacy Code

Old flat scripts were moved to `legacy/` for reference only. New projects should import from `mephc.*` rather than from root-level files such as `band.py` or `meep_lattice.py`.
