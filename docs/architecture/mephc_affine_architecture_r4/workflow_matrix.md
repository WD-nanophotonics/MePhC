# R4 Workflow Matrix

| consumer | identity | non-identity |
|---|---|---|
| direct basis | legacy unit square | canonical F transformed basis |
| reciprocal basis | identity reciprocal | inverse-transpose current basis |
| BZ | legacy square grid for compatibility | validated current Wigner-Seitz polygon |
| preview | canonical motif and outline | same transformed outline and motif |
| Band path | Gamma-X-M-Gamma | generic current-BZ vertices, BZ labels only |
| Berry auto | verified c4q | raw_bz |
| Berry explicit c4/c4q | verify then pass | reject |
| Berry raw | full legacy square grid | current BZ |
| EFS | legacy square grid/order | current BZ sampling |
| records | legacy identity geometry/task namespace | deformation/domain metadata |
| plots | derived from records | derived from records |

No local strain, motif deformation, supercell, material-index change, universal
symmetry inference, or scientific-record rewrite is included.
