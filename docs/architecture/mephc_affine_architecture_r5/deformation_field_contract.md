# Deformation-field contract

`DeformationField` is the single authority. `displacement(points)` returns
`u(r)`, `gradient(points)` returns `du_i/dr_j`, and derived values are
`deformation_gradient = I + gradient`, `jacobian = det(F)`,
`small_strain = (grad + grad.T)/2`, and the antisymmetric rotation part.

Zero and constant affine fields are canonicalized. Constant affine fields
wrap the existing `AffineTransform2D` exactly. Analytic fields require a
stable ID before persistent record writes; sampled fields use deterministic
bilinear interpolation and a grid digest. Finite values and Jacobian
conditioning are validated. No metric or curvature claim is made.
