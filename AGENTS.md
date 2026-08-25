# Relay-supervised scientific workflow

## Mandatory runtime entry point

This document describes policy; it is not the runtime enforcement mechanism. All MePhC relay, prelive, native and sandbox-publication work must enter via `/home/icy/MePhC/<native-worktree>/scripts/relayctl`. The launcher fixes the WSL root, Git worktree, Conda interpreter and `PYTHONPATH`; it rejects TriLatt, UNC/Windows worktrees, wrong interpreters, dirty execution trees, uncommitted prelive state, source-byte drift, and a moved `origin/main`. Courier is reached only through `relayctl courier`, which delegates to `tools/mephc-courier.ps1`. Direct Courier, Browser, Chrome and Gmail invocation are outside this path.

Runtime certificates, prelive records, native checkpoints, Courier requests and receipts are stored in ignored `.relayctl/`. Requests are plain text by default. Attachments require a separately identified committed remote audit artifact and are rejected by the ordinary bridge.
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
2. For a new request, use only validate -> preflight -> run. Continue from
   chat_ready; do not use the Browser skill, Chrome control, Gmail directly,
   or a second transport. Keep the calling process alive for at least the
   configured workflow window plus 60 seconds (the default is 600 seconds).
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
request. The exact ordinary sequence is:

python -m chat_courier.cli validate <request-dir>
python -m chat_courier.cli preflight <request-dir>
python -m chat_courier.cli run <request-dir>

preflight must emit chat_ready before run. Never set
CHAT_COURIER_PROFILE, AGENT_RELAY_CHATGPT_PROFILE, or
CHAT_COURIER_PROFILE_DIRECTORY during ordinary Agent work; never point
Courier at a user's normal Chrome user-data tree. A registered ChatGPT
conversation must be reused exactly. Do not register a replacement URL merely
because of an access or browser error.

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
