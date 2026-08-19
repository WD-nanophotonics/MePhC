# Persistent Git Push Note

## WSL GitHub authentication

When this WSL workspace pushes to GitHub over HTTPS, do not conclude that credentials are missing merely because plain WSL Git reports `could not read Username`. The credentials may be stored in Windows Credential Manager and available to Windows Git Credential Manager.

For this machine, use the installed Windows helper through its WSL-mounted short path (the short path avoids the space in `Program Files`):

```bash
GCM_INTERACTIVE=Never GIT_TERMINAL_PROMPT=0 \
git -c credential.helper=/mnt/c/PROGRA~1/Git/mingw64/bin/git-credential-manager.exe \
  push origin main
```

Before reporting a push failure, check both sides without exposing secrets:

```bash
git config --show-origin --get-all credential.helper
cmdkey.exe /list
git ls-remote origin refs/heads/main
```

Never print, copy, or manually extract a password/token. After a successful push, verify that local `HEAD` equals `git ls-remote origin refs/heads/main`.

## Persistent Gmail task-intake note

When the user sends a standalone title that looks like a task or project title (for example, `<PROJECT> — TASK — <TITLE>`), treat it as a Gmail email subject unless the user explicitly says it is not email-related. Do not preserve the concrete title as a default or historical task value.

Before implementing the task:

1. Read/search the corresponding Gmail message or thread first.
2. Treat the email body, artifact instructions, attached files, and referenced paths as the authoritative task contract.
3. Confirm the matched message is in the user's Inbox (add the INBOX label if it is not); do not send, archive, trash, or apply unrelated labels.
4. Only after reading and extracting the contract, inspect the local worktree and begin implementation.
5. If the title is ambiguous or no matching message can be found, ask for the sender, approximate date, message link, or pasted body instead of guessing.

This rule is an intake trigger, not permission to send email. Do not send or self-deliver email unless the user explicitly requests it.

## Windows and WSL environment handoff

Read this section before running tests, scripts, or the Gmail Courier workflow. It records the known-good paths and avoids repeating environment diagnosis.

### Canonical locations

- MePhC WSL worktree: `/home/icy/MePhC`.
- TriLatt WSL coordination worktree: `/home/icy/TriLatt`.
- Windows-visible Courier staging root: `/mnt/c/Users/icywo/PycharmProjects/MePhC-Windows`.
- Gmail Courier source: `/mnt/c/Users/icywo/PycharmProjects/GmailCourier`.
- Windows Python used by Courier and pytest: `C:\Users\icywo\AppData\Local\Programs\Python\Python312\python.exe`.

The active source repository is the WSL MePhC worktree. The Windows MePhC-Windows directory is Courier staging, not a second source repository.

### Test environment facts

- The single canonical project environment is `/home/icy/miniconda3/envs/mp/bin/python`. It provides pytest, NumPy, SciPy, Shapely, and Meep/MPB.
- Run normal MePhC work only from WSL using that environment:

```bash
cd /home/icy/MePhC
/home/icy/miniconda3/envs/mp/bin/python -m pytest -q
/home/icy/miniconda3/envs/mp/bin/python -m compileall -q mephc tests
git diff --check
```

- WSL `/usr/bin/python3` and `/home/icy/miniconda3/bin/python` are base interpreters, not the project environment. They may lack pytest and scientific packages; do not switch to Windows or create a second environment when the `mp` environment is available.
- Windows Python 3.12 is reserved for the Gmail Courier transport. It is not the normal MePhC test or development environment. Do not copy the source tree to Windows for ordinary work.
- Do not record one-off test counts, commit hashes, task names, URLs, timestamps, or current-work status in this file. Re-run checks when current results are needed.

### Sandbox and editing facts

- Direct PowerShell commands and direct edits through WSL UNC paths can intermittently fail with `helper_unknown_error` or sandbox setup errors. This is an execution-layer limitation, not evidence that the repository is broken.
- Prefer `wsl.exe -d Ubuntu -- bash -lc "..." ` for WSL reads and commands. If the patch helper cannot reach a WSL path, create the patch in a writable staging file with `apply_patch`, then apply the resulting diff with `git -C /home/icy/MePhC apply`. Do not create a second source worktree.
- Clean only exact temporary files/directories created for the current run. Never use broad recursive deletion against a workspace or home directory.

## Courier transport contract for Codex Agents

This is the authoritative project-side procedure for the Chat relay. It exists to prevent an Agent from changing the configured command, choosing an unsupported test path, using direct browser/Gmail tools, or misdiagnosing a Codex audit block as a Courier failure. Runtime URLs, project names, task IDs, correlation IDs, keywords, message contents, and timing values must come from the current request or local configuration; they must never be copied into this file as defaults.

### Scope and authorization

- Use this procedure only when the user has explicitly authorized the current message to be sent to the configured ChatGPT conversation.
- The Courier is an external side-effect transport. Before creating `READY`, the Agent must state the runtime target conversation, runtime identifiers, and message purpose. Do not write those values into persistent instructions.
- Do not infer authorization from a Python filename, a previous task, or a stale request directory.
- Do not ask the user to run the command manually merely because a different Agent previously received a sandbox denial. First report the exact denied path, command, and policy error.

### Canonical paths

- MePhC source and tests: `/home/icy/MePhC`.
- Courier source: `C:\Users\icywo\PycharmProjects\GmailCourier`.
- Windows Courier staging: `C:\Users\icywo\PycharmProjects\MePhC-Windows`.
- Outbox root: `C:\Users\icywo\PycharmProjects\MePhC-Windows\.courier_outbox`.
- The Windows staging directory is not a second MePhC source tree. Do not copy MePhC there for ordinary development or testing.

### Required file protocol

Create exactly one new directory per request, using runtime values supplied by the caller:

```text
<OUTBOX_ROOT>/<PROJECT_ID>/<UNIQUE_TASK_ID>/
```

Write these files in this order:

1. `request.json`
2. `message.txt`
3. `READY` last

The first two files must be complete before `READY` is created. Do not reuse a task directory, request ID, correlation ID, or READY file.

The manifest must contain:

```json
{
  "version": 1,
  "operation": "chat-send",
  "request_id": "<UNIQUE_REQUEST_ID>",
  "project_id": "<PROJECT_ID_FROM_CURRENT_REQUEST>",
  "correlation_id": "<UNIQUE_CORRELATION_ID>",
  "task_id": "<UNIQUE_ASCII_TASK_ID>",
  "keyword": "<UNIQUE_ASCII_KEYWORD>",
  "chat_url": "<CHAT_URL_FROM_CURRENT_REQUEST>",
  "workflow_window_seconds": "<WINDOW_FROM_CURRENT_REQUEST_OR_CONFIG>",
  "message_file": "message.txt"
}
```

Use the protocol's required encoding and validation rules. The Chat URL and every identifier must be taken from the current request or approved local configuration. Never put a real URL, ID, subject, or message from one task into examples, fixtures, defaults, or a database record used by another task.

### Only supported send command

Use the configured Courier runtime and module exactly as follows; substitute only values resolved for the current machine and request:

```text
<CONFIGURED_COURIER_RUNTIME> -m <CONFIGURED_COURIER_MODULE> chat-send-request --request <REQUEST_DIRECTORY>
```

Do not substitute an ad-hoc test command for the configured send operation. Do not pipe a prompt through a different CLI. Do not use direct Chrome, Gmail, Browser, or Gmail connector tools for this relay.

### Submission and receive states

- Keep the same process alive until it emits `"event": "chat_submitted"`.
- `chat_submitted` confirms Chat submission only. It does not confirm a Gmail response.
- Never start a second send while the first process is alive or while its `receipt.json` is being written.
- For a closed loop, run the configured receive operation separately with the caller-provided wait window, polling interval, lookback, runtime identifiers, and expected artifact. Do not copy these values from an earlier task.
- `gmail_received` means the validated delivery is in the project inbox.
- `gmail_candidate` is not a timeout. Inspect its `candidate_path/body.txt` and attachment `result.json`; a natural-language or non-ASCII subject can be a valid same-correlation response.
- If the Chat response explicitly says not to start the next phase automatically, accept the current result and stop. Do not invent a next task.

### Codex audit and failure reporting

A local `READY` file is only the Courier outbox trigger; no network action occurs unless the Courier command is actually started. Nevertheless, Codex may classify a populated outbox as a possible external data egress. If the safety layer blocks an operation:

1. Do not claim that Python, WSL, Gmail, or Courier failed.
2. Record the exact path, exact command, exact tool, and complete error text.
3. State whether Python started, whether `receipt.json` exists, and whether `chat_submitted` appeared.
4. Do not retry with `chat-test`, direct browser control, or a second task ID.
5. A dry-run may validate a synthetic request in an isolated directory, but it must not invoke Courier or contain private project status.

Courier-side improvements should expose separate operations for `validate-only`, `create-ready`, `submit`, and `poll`; emit machine-readable permission/configuration/submission errors; and provide a dry-run that cannot send. Tests must use generated synthetic values and must not persist real URLs, IDs, subjects, or project data. The Agent must never guess which stage failed.

## Handoff hygiene

This file contains only durable operating rules. It is not a task ledger, message archive, URL registry, or database of current work. Runtime values belong in the current request and its isolated request directory. When updating this file, use placeholders and abstract examples; remove one-off URLs, identifiers, timestamps, branch names, commit hashes, email subjects, response text, and test results before committing.

