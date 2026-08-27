# MePhC runner

This package is the machine-enforced Windows-control/WSL-work boundary for
MePhC. The Windows source/control root is
`C:\Users\icywo\PycharmProjects\MePhC-Windows`. The WSL worker accepts
immutable JSON jobs from `/home/icy/.local/state/mephc-runner/MEPHC/runner/jobs`
and executes an exact commit only from a detached clean ext4 checkout under
`/home/icy/.cache/mephc-runner/checkouts/<commit-sha>`.

The public operations are `doctor`, `validate`, `change`, `worktree`, `prelive`,
`native`, `publish`, and `courier`. `validate` runs selected committed
`tests/*.py` targets without materializing source. A change containing any
unchanged declared file is rejected before a durable job is created, with a
structured safe next tool. Arbitrary executables, roots, interpreters, project
identities, browser profiles, and Chat destinations are not accepted.

The Windows broker is a non-blocking supervised process. It updates its own
heartbeat while a materializer runs, binds each child PID to a random dispatch
token, and terminates only that process tree after the bounded deadline. A
timeout, broker restart, lost heartbeat, or interrupted transaction becomes
`recovery_required`; it never authorizes automatic replay. Change recovery can
only verify an attested commit, restore a persisted preimage journal, or prove
that the transaction never started. Job status exposes phase, progress age,
deadline, broker/worker health, and the single safe next tool.

Capabilities and blocker discovery use a durable `active-jobs.json` index
maintained transactionally by submission and worker state transitions. The
index contains only nonterminal, recovery-required, and orphan identities;
selected-job status still reads the authoritative per-job state. This keeps
startup bounded as historical terminal jobs accumulate. Admission retries a
disconnected backend once only for read-only tools and returns structured
disconnect identity for all other calls without replaying them.

The scheduled broker is configured to remain available on battery power and
when the machine leaves idle state. After cwd admission, the Windows connector
checks the build-bound heartbeat and starts a stopped broker task before it
launches the WSL MCP child. Doctor results are reused only while current worker
and broker heartbeats are fresh, mutually build-bound, and healthy; an old
successful certificate cannot conceal a stale runtime.

The only public Windows entry point is
`%LOCALAPPDATA%\MePhCRunner\mephc-runner.cmd`. It supplies the fixed
PowerShell execution-policy boundary and delegates to the typed client.
Installation is an explicit two-phase transaction: run `bootstrap.ps1
-Install`, let that command exit so Task Scheduler can release the execution
host, then run the same committed script with `-Verify`. The first phase saves
a build-bound pending credential and the previous Windows/WSL versions. The
second requires a fresh matching broker heartbeat plus doctor and health; a
failure restores the recorded versions instead of leaving a mixed install.

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
