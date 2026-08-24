# Relay-supervised scientific workflow

This repository is part of an automatic, relay-supervised workflow. The
registered supervisor Chat reached through GmailCourier is an operational
control channel, not a request for the human to manually copy instructions
back into this conversation.

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

## Audit publication and promotion protocol

origin/sandbox is the mandatory remote audit branch for work in progress.
Any source code, test, analysis script, numerical reduction logic,
classification logic, or other executable logic that materially affects a
scientific conclusion must be copied into the repository, committed, and
pushed to origin/sandbox before completion is reported. This also applies to
temporary conclusion-producing scripts created outside the repository.

Sandbox publication makes an implementation available for supervisor
inspection only. main is the accepted baseline. Promotion of an exact
sandbox commit to main requires explicit supervisor authorization after
inspection of the real remote diff and supporting evidence. Supervisor silence
never authorizes main promotion. Corrective commits remain on sandbox until
that authorization.

Completion reports involving auditable code must include:

CODE_CHANGE=NONE|SANDBOX_ONLY|SANDBOX_AND_AUTHORIZED_MAIN_PROMOTION
BASE_MAIN_SHA=<sha>
SANDBOX_HEAD_SHA=<sha>
AUDIT_DIFF_RANGE=<base>..<sandbox-head>

Use CODE_CHANGE=NONE only when no auditable implementation or
conclusion-producing logic changed.

## Scientific audit invariants

Cached or previously computed scientific results must never be reused by
coordinate alone when additional physical identity fields exist. Reuse must
match complete physical provenance; ambiguous collisions fail closed; a
human-readable rounded coordinate label is never a physical cache identity.

Distinguish NOMINAL_Q (requested quadrature coordinate), EVALUATED_Q
(actual solved target_q), and MANIFEST_Q. Physical cache identity uses
EVALUATED_Q plus complete provenance. Serialization or quantization must be
explicit and versioned; never describe a quantized evaluated coordinate as
exact nominal sampling.

Historical numerical evidence sampled at explicitly known coordinates slightly
different from nominal coordinates may be accepted only through explicit
perturbed-node error analysis. It must never be silently relabeled as exact
nominal sampling. Large raw evidence may remain external when required, but
any conclusion based on it must bind the exact external artifact by
cryptographic digest and publish deterministic reduction logic plus compact
trace evidence on sandbox.

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
