# Audit publication and promotion protocol

For work in this repository, `origin/sandbox` is the mandatory remote audit
branch for work in progress. Any source code, test, analysis script, numerical
reduction logic, classification logic, or other executable logic that
materially affects a scientific conclusion must be copied into the repository,
committed, and pushed to `origin/sandbox` before completion is reported. This
also applies to temporary conclusion-producing scripts created outside the
repository, even when no production source file changed. Agent confidence
does not waive this requirement.

Sandbox publication means only that the implementation is available for
supervisor inspection. `main` is the accepted baseline. Promotion of an exact
sandbox commit to `main` requires explicit supervisor authorization after
inspection of the real remote diff and supporting evidence. Compact control
evidence required to audit classification logic should accompany the scripts
when reasonably small. Do not interpret supervisor silence as authorization to
move `main`.

Corrective commits remain on `sandbox` until supervisor seal or promotion
authorization. Supervisor silence never authorizes main promotion.

Scientific audit invariant: cached or previously computed scientific results
must never be reused by coordinate alone when additional physical identity
fields exist. Reuse must match complete physical provenance, ambiguous
collisions fail closed, and a human-readable rounded coordinate label is never
a physical cache identity.

Completion reports involving auditable code must include:
Use `CODE_CHANGE=NONE` only when no auditable implementation or conclusion-producing logic changed.


```text
CODE_CHANGE=NONE|SANDBOX_ONLY|SANDBOX_AND_AUTHORIZED_MAIN_PROMOTION
BASE_MAIN_SHA=<sha>
SANDBOX_HEAD_SHA=<sha>
AUDIT_DIFF_RANGE=<base>..<sandbox-head>
```

Scientific sampling invariant: distinguish NOMINAL_Q (requested quadrature
coordinate) from EVALUATED_Q (actual solved target_q) and MANIFEST_Q. Physical
cache identity uses EVALUATED_Q plus complete provenance. Any serialization or
quantization must be explicit and versioned; never describe a quantized
evaluated coordinate as exact nominal sampling.

Historical numerical evidence sampled at explicitly known coordinates slightly
different from nominal coordinates may only be accepted through an explicit
perturbed-node error analysis; it must never be silently relabeled as exact
nominal sampling. New computations should avoid such quantization unless
explicitly authorized and versioned.

Large raw scientific evidence may remain external when repository size or
privacy policy requires it, but any scientific conclusion based on that
evidence must bind the exact external artifact by cryptographic digest and
publish enough deterministic reduction logic and compact trace evidence on
`sandbox` for supervisor audit.
