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

When the user sends a standalone title that looks like a task or project title (for example, `MePhC — TASK — ...`), treat it as a Gmail email subject unless the user explicitly says it is not email-related.

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
- The full current MePhC suite was verified in the `mp` environment: 187 passed and 27 subtests passed.

### Sandbox and editing facts

- Direct PowerShell commands and direct edits through WSL UNC paths can intermittently fail with `helper_unknown_error` or sandbox setup errors. This is an execution-layer limitation, not evidence that the repository is broken.
- Prefer `wsl.exe -d Ubuntu -- bash -lc "..." ` for WSL reads and commands. If the patch helper cannot reach a WSL path, create the patch in a writable staging file with `apply_patch`, then apply the resulting diff with `git -C /home/icy/MePhC apply`. Do not create a second source worktree.
- Clean only exact temporary files/directories created for the current run. Never use broad recursive deletion against a workspace or home directory.

### Courier closed-loop procedure

- Do not use direct Chrome or Gmail tools for the Chat relay. Use the Python Courier project.
- Outbound requests use `.courier_outbox/<PROJECT>/<TASK>/request.json`, `message.txt`, and `READY` (create `READY` last). Every request needs a unique ASCII `task_id`, `request_id`, `keyword`, and correlation ID; use `workflow_window_seconds: 360`.
- Invoke Courier with Windows Python and `PYTHONPATH=C:\Users\icywo\PycharmProjects\GmailCourier`:

```text
wsl.exe -d Ubuntu -- cmd.exe /c "set PYTHONPATH=C:\Users\icywo\PycharmProjects\GmailCourier && C:\Users\icywo\AppData\Local\Programs\Python\Python312\python.exe -m gmail_courier.cli chat-send-request --request C:\Users\icywo\PycharmProjects\MePhC-Windows\.courier_outbox\<PROJECT>\<TASK>"
```

- Wait for the same process to emit `chat_submitted`; never duplicate a still-running send. Then run `sync_until_received` with `max_seconds=360`, `interval_seconds=10`, the exact project/task/keyword/correlation ID, and expected `result.json`.
- `chat_submitted` confirms submission only. `gmail_candidate` is not a timeout: inspect its `candidate_path`, `body.txt`, and attachment `result.json`. Chat subjects may be natural-language or non-ASCII, so Courier can deliberately classify a valid same-correlation message as a candidate.
- If Chat says `Do not start E3 automatically`, stop after accepting the current result. Do not infer a stop from a candidate event or from the absence of an exact formal subject.

