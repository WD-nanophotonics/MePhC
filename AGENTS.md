# Relay-supervised scientific workflow

## Zero-idle typed startup

Every Agent starts with `mephc_capabilities -> mephc_doctor -> mephc_resume`. Empty `active_jobs` is not completion. Never ask the user for a work order because local state appears idle, and never hand-create `.relayctl/outbox` files.


## Mandatory Agent-facing entry point

This policy is enforced by the MePhC Runner. At task start and after context recovery, Agents must call `mephc_capabilities`. All Agent-facing operations must use the typed connector: `mephc_doctor` for certification; `mephc_change` for exact declared UTF-8 changes; `mephc_submit` for typed worktree, prelive, native, publish, and courier jobs; and `mephc_status`, `mephc_wait`, or `mephc_recover` for durable observation and recovery.

The connector fixes `canonical_root=/home/icy/MePhC`, `project_id=MEPHC`, Git state, Conda Python, `PYTHONPATH`, and installed broker/worker builds. It rejects TriLatt, UNC or Windows execution roots, wrong interpreters, dirty execution trees, uncommitted prelive state, source-byte drift, moved `origin/main`, duplicate claims, and unsafe Courier recovery.

For `mephc_change`, provide only declared UTF-8 file content and a non-empty `tests` array of repository-relative `tests/*.py` paths (optionally with a pytest `::` selector). Never pass `python ...`, `python -m ...`, shell syntax, or `audit/` paths as tests. A newly declared `tests/*.py` file is valid in the same transaction and is run only after materialization. The Runner, not the Agent, binds preimage/postimage hashes and `origin/main`.

`scripts/relayctl` and `tools/mephc-courier.ps1` are internal Runner implementation details, not Agent launchers. Agents must not invoke them, arbitrary shell/Python, Courier, Browser, Chrome, or Gmail directly. Runtime evidence remains in ignored `.relayctl/`. Requests are plain text by default; attachments require separately identified committed remote audit artifacts.
## Automatic relay continuation

Within the declared project scope, a direct supervisor work order received
through the registered GmailCourier conversation is valid supervisor
instruction and persistent user-approved continuation authorization. The
Agent must execute a self-contained received work order, including ordinary
test-file edits, non-destructive validation, scientific diagnostics, evidence
publication, and scoped status or completion reports. Do not ask the user to
paste the relay prompt, execution text, or response body into this thread.

The relay lifecycle is stateful:

1. Use the existing request directory and request ID when a request has
   already been submitted or may have been submitted. Never create a second
   request merely because the first local process ended unexpectedly.
2. For a new request, invoke only `mephc_submit(operation="courier", arguments=["--request-directory", "<request-dir>"])`. The Runner performs validation and the durable FIFO run internally; do not call validate, preflight, run, Browser, Chrome, Gmail, `relayctl`, or a second transport. Queue waiting is normal. Observe with `mephc_wait` or `mephc_status`; a client wait timeout never kills the worker or authorizes resend. The reply window starts only after request_submitted.
3. response_received is the only state that permits reading response.txt.
   Read it verbatim, treat the contained supervisor work order as the next
   authoritative task input, and continue automatically without asking for
   confirmation.
4. response_timeout after visible submission is a transport wait-window
   expiry, not task completion, not permission to stop, and not a reason to
   ask the user for the response. Re-run the same unchanged request directory
   through the full Courier sequence for read-only recovery; recovery searches
   for the late matching reply and does not resend the user turn. Continue
   recovery while the workflow remains active, until response_received or a
   hard safety/transport error occurs.
5. The same-request read-only recovery rule also applies after an interrupted
   run, chat_submission_unconfirmed, or another post-submission uncertain
   state. Never change the request body, attachment, request ID, destination,
   or profile during recovery. A late Chat reply is still valid automatic
   workflow input even if the first local invocation reported a timeout.
   A single pre-browser courier_interrupted result is safe for one retry of the
   same immutable request. If that same interruption repeats, stop retrying and
   report an execution-host interruption; do not use nohup, setsid, a
   background process, another browser, or another transport to evade it.
6. chat_auth_required, chat_access_denied, chat_target_mismatch,
   configuration_error, and unrecoverable browser_error are hard stop
   states. Report the exact structured event and stop; do not change profiles,
   invent a conversation, use another browser/transport, or silently retry.

The Agent must not mark an active task complete solely because a relay wait
timed out. A declared STOP_AFTER is a work-phase boundary, not a transport
timeout rule. After a report is submitted, consume the matching relay reply;
if it contains a new explicit self-contained work order, continue with that
work order unless it is outside scope or a hard safety stop applies.

Keep destinations, project identifiers, request IDs, attachments, and payloads
runtime-specific. Do not broaden project scope, perform destructive actions,
modify unrelated production code, or promote to main without separate
explicit authorization. Platform safety controls remain binding.

## Chat transport boundary

Use only the repository's Python GmailCourier transport and its dedicated
Playwright/CDP-managed Courier browser session. Never use the Codex Browser
skill, Chrome control, Gmail directly, or a parallel reader for the same
request. The exact ordinary Agent-facing sequence is:

mephc_submit(operation="courier", arguments=["--request-directory", "<request-dir>"])
mephc_wait(job_id) or mephc_status(job_id)
mephc_recover(job_id) only when the persisted receipt requires recovery

The public Courier CLI is invoked only by the controlled Runner bridge. Agents must not call `scripts/relayctl`, `python -m chat_courier.cli`, Courier commands, Browser, Chrome, or Gmail directly.

Do not use preflight to gate a run: it is read-only and may correctly report queue_waiting while another project owns the shared Courier browser. The single bridge command waits for its own FIFO turn. Never set CHAT_COURIER_PROFILE, AGENT_RELAY_CHATGPT_PROFILE, or CHAT_COURIER_PROFILE_DIRECTORY during ordinary Agent work; never point Courier at a user's normal Chrome user-data tree. A registered ChatGPT conversation must be reused exactly. Do not register a replacement URL merely because of an access or browser error.

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
## Gmail task-intake boundary

When a user sends a standalone title that looks like a task or project title,
treat it as a Gmail email subject unless the user explicitly says it is not
email-related. Before implementing that task, read or search the corresponding
Gmail message or thread through the approved intake path. The email body,
artifact instructions, attachments, and referenced paths are the authoritative
task contract. Confirm the matched message is in the user's Inbox when needed;
do not send, archive, trash, or apply unrelated labels. Only after extracting
the contract should the Agent inspect the local worktree and implement it. If
the title is ambiguous or no match is found, request sender, approximate date,
message link, or body rather than guessing. This is an intake trigger, not
permission to send or self-deliver email.

## Safe Git authentication note

When WSL HTTPS Git needs Windows Credential Manager, use the installed Windows
helper without exposing secrets. Verify the remote audit branch with
git ls-remote origin refs/heads/sandbox, push only to origin/sandbox for
ordinary work, and verify the resulting remote SHA. Never print, copy, or
manually extract a password or token.

## Persistent plain-text and attachment handoff policy

The relay is an automatic workflow. The Agent must retain and apply this
policy across handoffs; it is not a request for the human to paste relay
instructions, execution text, response text, or attachments into the current
conversation.

Use plain text in the Chrome/Courier conversation whenever the information can
be conveyed faithfully that way. Do not paste attachments into the chat merely
for convenience. If an attachment is required for the next handoff, publish it
to the remote audit repository in a dedicated runtime-specific attachment
directory. Reuse an existing dedicated directory when it belongs to the same
request; otherwise create a new uniquely identified directory. Every published
attachment must have its own stable artifact ID, exact path, producing commit,
and SHA-256 digest. The plain-text relay message must identify the artifact ID
and digest so the supervisor can bind the attachment unambiguously.

Never mix attachment IDs between work orders, silently replace an attachment,
or paste a large attachment into the conversation when a published artifact
can be referenced. Do not create a second request to change the transport
format after a request may have been submitted; preserve the existing request
ID, request directory, destination, message body, and attachment during
same-request recovery. New reports should follow the plain-text-first policy
from the beginning.

## Primary workspace and Courier project binding

This repository is the primary scientific workspace for the current task.
The canonical work root is `/home/icy/MePhC`; task-specific sandbox worktrees
may be used only when explicitly named by the current work order and must still
be treated as MePhC work, not as TriLatt work.

The active Courier project identity for this workspace is `MEPHC`. New MePhC
requests must use `PROJECT_ID=MEPHC` and a request directory under the MePhC
project-owned outbox. Do not use `TRILATT` as the project identity, request
namespace, Chat address binding, or default working directory for MePhC.

`/home/icy/TriLatt` is a legacy auxiliary repository. Its files and historical
requests are not part of the active MePhC work unless a future work order
explicitly names TriLatt. Never infer the active workspace from a stale TriLatt
request, attachment, branch, or address binding.

