# First-BZ Algorithm

For a direct basis `A`, R2 forms the no-`2*pi` reciprocal basis `B=A^{-T}`.
For reciprocal integer neighbors `g != 0`, the first-zone half-plane is

`dot(g, k) <= dot(g, g) / 2`.

Starting from a finite bounding square, the implementation clips against
increasing reciprocal-neighbor shells.  It accepts only after polygon vertex
count and area stabilize and the area matches `abs(det(B))` within tolerance.
The result is canonicalized to an open counter-clockwise vertex list starting
at the rightmost vertex, with lowest-y tie break.

This is a Euclidean Wigner-Seitz construction.  It is intentionally not an
affine image of the old triangular or square polygon, and no generic K/M
label semantics are introduced.

The implementation is NumPy-only for the new kernel; no heavy geometry
dependency was added.
