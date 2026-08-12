# MePhC Affine Architecture R4

R4 migrates SqrLatt square-hole workflows to one canonical affine structure
authority and resolves the C4 hold point by candidate verification.

Scope:
- identity square-hole behavior remains legacy-compatible;
- non-identity uniaxial transforms use current direct/reciprocal bases and a
  reconstructed Wigner-Seitz BZ;
- explicit C4 reduction is rejected unless the complete structure verifier
  passes;
- TriLatt is read-only at its accepted hold ref;
- R5 is not authorized.

The payload is separate from scientific data and previous image archives. Solver
logs use /home/icy/miniconda3/envs/mp/bin/python with
PYTHONPATH=/home/icy/MePhC:/home/icy/SqrLatt.

Artifact index:
- preflight.json: repository, environment, dependency, and R3.1 gates.
- canonical_structure_contract.md: canonical truth source and adapters.
- c4_verification_contract.md: complete-structure C4 policy.
- workflow_matrix.md: identity/non-identity behavior.
- production_smokes.json and logs/: real MPB execution evidence.
- validate_r4.py and validator_negative_fixtures.py: deterministic evidence
  validator and isolated targeted fixture matrix.
- completion.json and artifact_manifest.json: final machine-binding closure.

Validation commands:
- python validate_r4.py --check-bundle --bundle-root .
- python validate_r4.py --check-worktrees --bundle-root . --mephc-root
  /home/icy/MePhC --trilatt-root /home/icy/TriLatt --sqrlatt-root
  /home/icy/SqrLatt --require-remote-equality
- python validator_negative_fixtures.py --bundle-root .

The final closure is complete only after the payload commit, metadata seal,
remote equality check, external receipt, and Gmail attachment round-trip.
