# MePhC Affine Architecture R3.1 Delivery Closure

This bundle closes the R3.1 delivery defects without changing production solver behavior. The committed `run_r3_1_smokes.py` replays real low-resolution TriLatt band, Berry, EFS, and tracked-K MPB entrypoints. It writes only below an explicitly supplied output root and never writes records.

The closure uses a non-self-referential model: a validated payload commit is followed by one metadata seal commit containing only `completion.json` and `artifact_manifest.json`. `validated_payload_refs.MePhC` identifies the seal parent. The final self-inclusive remote refs are recorded outside the repositories in `MePhC_Affine_Architecture_R3_1_Closure_Submission_Receipt.json`.

Replay from the MePhC root:

```bash
mp-python docs/architecture/mephc_affine_architecture_r3_1/run_r3_1_smokes.py --output-root "$R3_1_SMOKE_OUTPUT"
mp-python docs/architecture/mephc_affine_architecture_r3_1/validate_r3_1.py --check-bundle
mp-python docs/architecture/mephc_affine_architecture_r3_1/validate_r3_1.py --check-worktrees
```

The final worktree check is run only on the clean metadata seal commit. The external receipt and its final-validator log are intentionally untracked. No production Python, scientific data, R1/R2/R3 evidence, or SqrLatt content is changed. R4 was not started and is not authorized.
