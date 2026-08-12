# R6 validation report

The locked runtime probe confirms the interpreter, Meep, MPB, and ModeSolver. Both downstream adapters execute real TE supercell solves with generic q points.

SqrLatt passes 8 -> 12 with maximum absolute difference 0.0015805932529573408 and is accepted at resolution 12. It has five eligible (q, band) records.

TriLatt q1 passes 8 -> 12 and 12 -> 16, but q2 fails both comparisons. The q2 differences are 0.007766686443040127 and 0.006586148621552601. Per contract, the downstream state is BLOCKED_NONCONVERGED; no production response is claimed for TriLatt.

The validator checks required artifacts, digest equality, status consistency, sign algebra, and forbidden semantic leakage. Negative fixtures cover missing artifacts, bad digests, status mismatch, and protected metadata drift.

