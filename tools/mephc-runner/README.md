# MePhC runner

This package is the machine-enforced Windows-control/WSL-work boundary for
MePhC. The WSL worker accepts immutable JSON jobs from
`/home/icy/MePhC/.relayctl/runner/jobs` and invokes only
`/home/icy/MePhC/scripts/relayctl`.

The public operations are `doctor`, `worktree`, `prelive`, `native`, `publish`,
and `courier`. Arbitrary executables, roots, interpreters, project identities,
browser profiles, and Chat destinations are not accepted.

Runtime state is ignored under `.relayctl/runner`. Source belongs on
`origin/sandbox`; the installed systemd unit is only a reproducible runtime
copy bound to the source SHA-256 recorded by bootstrap.
