# MePhC runner

This package is the machine-enforced Windows-control/WSL-work boundary for
MePhC. The Windows source/control root is
`C:\Users\icywo\PycharmProjects\MePhC-Windows`. The WSL worker accepts
immutable JSON jobs from `/home/icy/.local/state/mephc-runner/MEPHC/runner/jobs`
and executes an exact commit only from a detached clean ext4 checkout under
`/home/icy/.cache/mephc-runner/checkouts/<commit-sha>`.

The public operations are `doctor`, `worktree`, `prelive`, `native`, `publish`,
and `courier`. Arbitrary executables, roots, interpreters, project identities,
browser profiles, and Chat destinations are not accepted.

The only public Windows entry point is
`%LOCALAPPDATA%\MePhCRunner\mephc-runner.cmd`. It supplies the fixed
PowerShell execution-policy boundary and delegates to the typed client.

Runtime state and Git object caches are outside every checkout. New jobs use
schema v2 and bind the exact Windows root, source commit, cached `origin/main`,
and state epoch. Legacy v1 jobs remain inspectable and recovery-only. Source
belongs on `origin/sandbox`; this migration never moves `main` or pushes.
