# Compatibility Matrix

| Surface | Before R2 | R2 behavior | Evidence |
| --- | --- | --- | --- |
| `Band(lattice_type=...)` | named triangular/square MPB bases | same call shape; named basis delegates to `BravaisLattice2D` | `test_r2_kernel.py`, R1 locks |
| `Lattice(...)` | legacy real-space generators | same signature; optional canonical model adapter | `test_r2_kernel.py`, R1 locks |
| `maketriangularlattice` | alternating-row site order | same point order for identity model | R1 lock 01, R2 solver/adapter test |
| `TriangularKSpace.first_bz_poly` | named triangular polygon | canonical Wigner-Seitz polygon for default model | R1 lock 02, R2 BZ test |
| `SquareKSpace.first_bz_poly` | square polygon | canonical Wigner-Seitz polygon | R2 kernel test |
| TriLatt geometry identity | config/Band/k-space consumers | `config.canonical_lattice()` shared by all three | `test_r2_identity_migration.py` |
| SqrLatt | downstream consumer | read-only; tree digest unchanged | R2 integrity report |

No legacy public API was removed, and no geometry ID or record-key format was
changed.
