# Workflow guard matrix

| field capability | preview | primitive BZ/Band | primitive Berry/EFS | supercell reciprocal |
| --- | --- | --- | --- | --- |
| GLOBAL_AFFINE_PERIODIC | yes | yes | yes | not needed |
| SUPERCELL_PERIODIC, verified | yes | no | no | yes, labeled supercell |
| APERIODIC_LOCAL | yes | reject `E_R5_PRIMITIVE_SEMANTICS` | reject same code | reject |

No C3/C4 reduction is inferred for local or supercell fields.
