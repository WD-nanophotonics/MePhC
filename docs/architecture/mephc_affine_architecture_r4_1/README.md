# MePhC R4.1 Validation Integrity Corrective

This directory is an evidence-only corrective for R4. Production code,
scientific data, SqrLatt, TriLatt, and the existing R1-R4 evidence are frozen.

The validator has two explicit modes:

    python validate_r4_1.py --check-bundle --bundle-root <bundle>
    python validate_r4_1.py --check-worktrees --bundle-root <bundle> --mephc-root <root> --sqrlatt-root <root> --trilatt-root <root> --expected-mephc-ref <seal> --expected-payload-ref <payload>

Bundle mode is hermetic: it reads only the supplied bundle. Worktree mode is
explicit: every repository root and expected ref is supplied by the caller.
The negative-fixture runner copies the bundle into isolated temporary
directories and invokes the public validator as a subprocess for every case.

The two-commit topology is payload P, then a metadata-only seal S. The
completion object records P and the external receipt records S; no commit is
permitted after S.
