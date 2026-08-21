# E7I.1G C7 coordinate semantics and impact audit

C7 preserves exact evaluated-q cache identity and makes nominal/requested versus
evaluated/result coordinates explicit in the compact trace. No MPB was run.

Across 50,688 records, 18,584 are bitwise exact. The maximum displacement among
the 32,104 mismatches is 5.289834379830108e-13, far below h=0.001 and all
mesh-edge scales. The 1,704 rounded collision groups have zero cross-physical
identity collisions; their maximum nominal separation is
2.482534153247273e-16.

The empirical guard is sub-1e-9 relative to the refined flux anchors, but C7
does not upgrade the scientific seal because 24,152 records are not recognized
by the currently implemented exact/decimal10/decimal12 mapping classes. They
remain an explicit unresolved historical mapping rather than being silently
called canonical. No broad recomputation is authorized.

The compact trace stores nominal_q_exact, evaluated_q_exact, coordinate mapping
class, and result digest in each chunk digest. C7 replay is solver-neutral and
numerically identical to C5. The branch is sandbox-only and main remains
frozen.
