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

For interactive WSL use, `mephc-runtime sync` creates the exact committed
local `sandbox` checkout and atomically updates
`/home/icy/.local/share/mephc-runtime/current`. `mephc-runtime path` prints the
validated checkout. `mephc-runtime run --project /home/icy/TriLatt -- <argv>`
runs an argument array from the downstream project directory with the `mp`
Conda environment and that checkout on `PYTHONPATH`, so relative outputs stay
in the downstream project. This human interface is not an Agent launcher;
Agents must use the typed MCP connector.

The retired `/home/icy/MePhC` source is handled only by
`home_cleanup.py inventory|archive|verify|apply`. Archive creation includes an
all-refs bundle, a restore drill, hashes, legacy `.relayctl` bytes, known loose
Home receipts/logs, and TriLatt file guards. `apply` requires the verified
archive path and exact keep commit; unknown Home items are always retained.

The older residue inventory/retention/cleanup utilities in this directory are
historical audit artifacts tied to `/home/icy/MePhC/.relayctl`; they are not
installed launchers and are retired after archival. Legacy v1 jobs remain
queryable in durable state. Recovery that requires the archived source fails
closed with `LEGACY_ARCHIVED_RECOVERY_UNAVAILABLE` until an operator restores
the archive; it is never automatically replayed.
