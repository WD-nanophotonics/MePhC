# Deformation Contract

TriLatt geometry configuration exposes `stretch_factor` and
`stretch_angle_degrees`. The factor must be finite and positive; the affine
matrix must remain numerically well conditioned. `stretch_factor=1` is the
identity case, and its angle is canonicalized to preserve legacy behavior.

The deformation acts on the Bravais lattice vectors and leaves the local
polygon pattern and material parameters unchanged. Real-space geometry,
current reciprocal vectors, band paths, Berry sampling, EFS sampling, record
metadata, and geometry IDs all derive from the same canonical lattice model.
