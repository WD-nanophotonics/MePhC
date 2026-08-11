# Semantic Model

`reference_family` describes the intended Bravais family. `current_symmetry`
describes only the symmetry that is currently safe to use. A transformed
triangular lattice therefore retains `reference_family="triangular"` but has
`current_symmetry="generic_affine"` and `supports_legacy=False`.

The global deformation is column-vector affine geometry:

`A_current = F A_reference`, where `F = I + (s - 1) n n^T` and
`n = (cos(theta), sin(theta))`.

The identity transform is canonicalized so old geometry IDs and old workflows
remain unchanged. The model deliberately does not infer point-group symmetry.
