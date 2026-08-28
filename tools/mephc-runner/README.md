# MePhC runner

Side-effect calls are durably indexed by admission request ID before validation.
After any transport disconnect, `mephc_request_status` reconciles the original
request without replaying it. Native execution is exposed only as
`mephc_native(recipe_id)` and is gated by the active work-order recipe digest,
invocation budget, and a passing prelive for the exact source SHA. Generic
`mephc_submit` no longer accepts doctor, prelive, native, or publish.

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

`mephc_runtime_attest` reports the source HEAD and installed source commit and binds
admission, MCP, broker and worker builds, import-time module hashes, state
epoch, infrastructure source bytes, and live heartbeat freshness. A source-only
commit does not make the runtime stale when all installed infrastructure bytes
still match. Doctor cannot be created or reused while
that attestation is incoherent. The no-argument lifecycle tools are deliberately
narrow: `mephc_runtime_reload` restarts only the installed broker/worker and
rotates the calling admission backend; `mephc_runtime_activate` accepts only a
clean, published `sandbox` whose delta from the installed source is confined
to infrastructure. Activation runs a fixed test set, stages the exact commit,
and restores the prior Windows, WSL, admission and config snapshot if install
or post-install attestation fails.

Doctor emits an environment-certificate v2 bound to the Runner build, state
epoch, interpreter, fixed roots, `origin/main`, and fresh runtime health. Its
issue-time source and worktree are audit metadata. Validate/prelive separately
bind the requested source commit and detached execution checkout, and their
attestation records both that SHA and the environment-certificate digest.
Legacy v1 certificates remain queryable and are executable only at their exact
recorded checkout and HEAD. Missing or mismatched certificates are rejected
before a durable job directory is created.

`mephc_retention_worker_reload` is a compatibility name for a fixed restart of
the shared durable `mephc-runner.service`; it does not imply a dedicated
retention queue. Health must prove a new stable worker start ID, WSL PID, and
start time while the build, loaded module hash, installed source, state epoch,
and fresh Windows broker identity remain unchanged. Timestamp-only movement or
an active/recovery-required job fails closed.

The scheduled broker is configured to remain available on battery power and
when the machine leaves idle state. It uses the consoleless `pythonw.exe`
launcher, and every admission-owned child uses `CREATE_NO_WINDOW`, so runtime
supervision cannot steal desktop focus. After cwd admission, the Windows connector
checks the build-bound heartbeat and starts a stopped broker task before it
launches the WSL MCP child. Doctor results are reused only while current worker
and broker heartbeats are fresh, mutually build-bound, and healthy; an old
successful certificate cannot conceal a stale runtime.
Task Scheduler executes `pythonw.exe windows_broker.py` directly so its restart
policy supervises the actual broker PID rather than a transient shell wrapper.
The admission shim launches only the installed Windows connector; it never
starts the WSL MCP server directly, so every admitted session passes through
the same broker-health gate.

The sole `mephc` MCP table is project-scoped in the trusted canonical
`.codex/config.toml`, with its `cwd` fixed to the exact Windows control root.
The installer atomically removes the former user-global table. This prevents
Desktop application-directory startup probes from disabling the server while
keeping MePhC tools absent from unrelated projects.

The only public Windows entry point is
`%LOCALAPPDATA%\MePhCRunner\mephc-runner.cmd`. It supplies the fixed
PowerShell execution-policy boundary and delegates to the typed client.
Installation is an explicit two-phase transaction: run `bootstrap.ps1
-Install`, let that command exit so Task Scheduler can release the execution
host, then run the same committed script with `-Verify`. The first phase saves
a build-bound pending credential and the previous Windows/WSL versions. The
second requires a fresh matching broker heartbeat plus doctor and health; a
failure restores the recorded versions instead of leaving a mixed install.

Runtime state and Git object caches are outside every checkout. Ordinary jobs
use schema v2 and bind the exact Windows root, source commit, cached
`origin/main`, and state epoch. Hash-bound retention search uses schema v3 and
additionally binds the active work order, query digest, and installed Runner
build. Legacy v1 jobs remain inspectable and recovery-only. Source belongs on
`origin/sandbox`; this migration never moves `main`.

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

## Hash-bound retention inspection

`mephc_retention_search` accepts only `RETENTION_ID + expected_sha256` pairs
present in the active work order. It searches fixed Runner-owned roots in
index-first order, creates an idempotent durable read-only job, and reports
only opaque locators. `mephc_retention_inspect` rehashes the selected bytes on
every read and provides metadata, outline, bounded JSON pages, or a generic
numeric summary. Typed responses redact host paths and identities. The search
tool is never replayed across an admission disconnect; inspect is read-only
and may be replayed once. `SEARCH_INCOMPLETE` must never be interpreted as
`NOT_FOUND_EXHAUSTIVE`.

## Work-order contract and preflight

The canonical `mephc-work-order-contract-v1` JSON binds the work-order ID,
required typed capabilities, authorized actions and retention ID/hash pairs.
A read-only legacy adapter normalizes direct, prefixed, CRLF and historically
escaped-newline retention fields into that same schema. Retention submission
and worker validation use this shared parser. `mephc_work_order_preflight`
returns the contract digest, available and missing capabilities, fixed-policy
conflicts, and runtime attestation. Missing tools and forbidden shell, WSL,
browser, arbitrary path/process control, or main-promotion requests stop before
any durable job is created.
