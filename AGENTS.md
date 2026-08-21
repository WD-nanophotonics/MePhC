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

For the C4/C5/C6 exact-domain audit, `geometry_generator.py`,
`trace_generator.py`, the strict reducers, and the exact-q identity/cache
modules are the current authoritative audit surface. Full generated meshes,
raw manifests, and solver logs remain local execution artefacts. If a work
order changes no auditable code or conclusion-producing logic, report
`CODE_CHANGE=NONE`; otherwise completion is incomplete without an inspectable
sandbox commit. Corrective commits remain on `sandbox` until supervisor
seal/promotion authorization, and supervisor silence never authorizes main
promotion.

Scientific audit invariant: cached or previously computed scientific results
must never be reused by coordinate alone when additional physical identity
fields exist. Reuse must match complete physical provenance, ambiguous
collisions fail closed, and a human-readable rounded coordinate label is never
a physical cache identity.

Completion reports involving auditable code must include:

```text
CODE_CHANGE=NONE|SANDBOX_ONLY|SANDBOX_AND_AUTHORIZED_MAIN_PROMOTION
BASE_MAIN_SHA=<sha>
SANDBOX_HEAD_SHA=<sha>
AUDIT_DIFF_RANGE=<base>..<sandbox-head>
```
