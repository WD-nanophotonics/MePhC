# E7I.1G C9 hash-bound source recovery

C9 recovers the historical C7 source by exact SHA-256 rather than by filename
or matching aggregate flux. The source remains an external execution artifact;
it is never committed to Git.

The C9 runner validates the deterministic logical slots, including rule,
triangle index, and sample index. It binds each association to exact nominal
and evaluated coordinates, a physical-identity digest, and a digest of the
canonical stored result object. It emits only compact chunk digests and a
bounded direct witness fixture.

The C9 weighted perturbation bound is:

`L_guard * SUM_ABS_WEIGHT_DQ`

and the secondary maximum-displacement cross-check is:

`AREA_VK * L_guard * MAX_DQ`.

No MPB or physical recalculation is performed.
