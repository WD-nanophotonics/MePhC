# Periodicity and capability contract

Only a `PeriodicSupercellField` with a nonsingular integer replication matrix
and a passing equivalent-boundary displacement check may expose a supercell
direct/reciprocal basis. Its metadata is explicitly labeled `supercell`.

An aperiodic field cannot call primitive BZ, high-symmetry, C3/C4, Band,
Berry, or EFS operations. Primitive labels are never inferred from the
reference lattice family. Supercell symmetry reductions are disabled by
default and no unfolding is implemented.
