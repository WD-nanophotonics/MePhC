# Audit publication and promotion protocol

For work in this repository, `origin/sandbox` is the mandatory remote audit
branch for work in progress. Any source code, test, analysis script, numerical
reduction logic, classification logic, or other executable logic that
materially affects a scientific conclusion must be committed and pushed to
`origin/sandbox` before completion is reported. This requirement applies to
experimental, provisional, corrective, and complete work; agent confidence
does not waive it.

Sandbox publication means only that the implementation is available for
supervisor inspection. `main` is the accepted baseline. Do not advance or
publish `main` merely because work appears correct or complete. Promotion of
an exact sandbox commit to `main` requires explicit supervisor authorization
after inspection of the real remote diff and supporting evidence. Corrective
commits remain on `sandbox` until an exact commit is sealed.

If a work order genuinely changes no auditable code or conclusion-producing
logic, report `CODE_CHANGE=NONE`. Otherwise, a changed-code completion report
is incomplete unless the corresponding remote sandbox commit exists and is
inspectable. Large raw numerical artifacts, binary caches, credentials, and
machine-specific secrets need not be committed; the executable logic that
generated, transformed, reduced, or classified such artifacts must remain
auditable.

Future completion reports involving changed or newly written auditable logic
must include:

```text
CODE_CHANGE=NONE|SANDBOX_ONLY|SANDBOX_AND_AUTHORIZED_MAIN_PROMOTION
BASE_MAIN_SHA=<sha>
SANDBOX_HEAD_SHA=<sha>
AUDIT_DIFF_RANGE=<base>..<sandbox-head>
```

Do not interpret supervisor silence as authorization to move `main`.
