# Current Architecture

## Repository boundary

The family is currently three separate repositories:

| Repository | Role | Current dependency |
|---|---|---|
| `MePhC` | reusable package and runnable examples | Meep/MPB, NumPy, SciPy, Shapely, Matplotlib |
| `MePhC-TriLatt` | triangular case workflows | `MePhC` via import/path or editable install |
| `MePhC-SqrLatt` | square case workflows | `MePhC` via import/path or editable install |

The runtime package is under `MePhC/mephc/`. The two consuming repositories
keep case configuration, task parameters, records, image generation, and
case-specific symmetry workflows.

## Current layers

1. **Geometry and pattern layer**: `mephc/lattice.py`, `mephc/patterns.py`,
   and `mephc/geometry.py`. `Lattice` creates direct-space sample points and
   `PolygonPattern` places polygons on those points. Case files also build
   normalized polygon or radius-dictionary patterns.
2. **Solver model layer**: `mephc/band.py`. `Band` owns physical defaults,
   the MPB `geometry_lattice`, high-symmetry aliases, material block creation,
   and conversion from case patterns to Meep geometry.
3. **Reciprocal and symmetry layer**: `mephc/kspace.py`. It contains
   `HighSymmetryPath`, `SquareKSpace`, and `TriangularKSpace`, including grid,
   Brillouin-zone, C3, and C4 helpers.
4. **Observable layer**: `mephc/berry.py` and `mephc/efs.py`. Berry uses an
   Abelian plaquette link variable; EFS stores k-points and frequencies and
   interpolates only for visualization.
5. **Plot and preview layer**: `mephc/plotting.py` and `mephc/preview.py`.
   Regular grids use direct plotting; irregular points use interpolation.
6. **Record and workflow layer**: `mephc/records.py` and
   `mephc/workflows.py`. TriLatt and SqrLatt still have local record lookup
   wrappers and local case runners, while shared save/output functions are in
   MePhC.

## Physical truth sources

The primary direct-space basis is currently encoded in `Band._make_geometry_lattice`:

- triangular: `basis1=(0.5, sqrt(3)/2)`, `basis2=(0.5, -sqrt(3)/2)`;
- square: `basis1=(1, 0)`, `basis2=(0, 1)`.

The same `Band` instance also derives `Gamma`, `K`, and `M` aliases. Case
configuration supplies motif parameters, while `create_unitcell` and case
builders decide how those parameters become normalized polygons. This is a
split truth source: lattice basis is in `Band`, motif rules are partly in
`Band` and partly in case configuration.

MPB receives the same `geo_latt` object. Cartesian reciprocal k-points are
converted at solver/observable boundaries with Meep's
`mp.cartesian_to_reciprocal`. The package convention is dimensionless
Cartesian reciprocal coordinates in the `2*pi/a` style used by the case
workflows; the conversion itself is not centralized in a context object.

## Workflow ownership

`Band` is the reusable solver facade. TriLatt and SqrLatt own case-specific
task parameters, symmetry reduction, record selection, and plotting blocks.
The case runners are therefore convenient click-run entry points but are not
yet thin adapters: both repositories duplicate `_resolve_existing_record`.

Simulation records and derived images are conceptually separated. Records
are dictionaries serialized by `mephc.records`; plots read records and can be
regenerated without MPB. Canonical records are reusable and may be overwritten;
archive records are optional. Existing data/image/diagnostics trees are
consumer-owned evidence, not package source.

## Main architectural risks

- Direct-space basis and motif semantics are not represented by one immutable
  geometry context.
- Reciprocal coordinates are conventional rather than typed; unit and `2*pi`
  assumptions are easy to bypass.
- `Band` combines geometry, solver setup, high-symmetry aliases, and observable
  convenience APIs.
- TriLatt and SqrLatt duplicate record lookup and task orchestration.
- Symmetry selection is case-owned. TriLatt checks polygon side counts for C3;
  SqrLatt applies square C4 expansion. Neither is a general full-structure
  symmetry verifier.
- The Abelian Berry implementation is band-by-band and has no non-Abelian
  treatment for degeneracies.

## R1 conclusion

The current implementation is usable for its two cases, but the highest-value
R2 work is to make coordinate conventions and physical geometry ownership
explicit before adding affine deformation. No runtime change is made by R1.
