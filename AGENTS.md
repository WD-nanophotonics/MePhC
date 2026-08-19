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

- WSL `/usr/bin/python3` and `/home/icy/miniconda3/bin/python` do not provide the project test stack used here (`pytest`, NumPy, and other project packages). Do not spend time retrying `pytest` there.
- Windows Python 3.12 has pytest and NumPy, but the Windows process cannot reliably import a package directly from the WSL UNC path in this setup.
- For pure-data tests, copy `/home/icy/MePhC` to an explicitly named temporary directory under the Courier staging root, then run Windows Python with that copy on `PYTHONPATH`:

```bash
cp -a /home/icy/MePhC /mnt/c/Users/icywo/PycharmProjects/MePhC-Windows/.test_copy
wsl.exe -d Ubuntu -- cmd.exe /c "set PYTHONPATH=C:\Users\icywo\PycharmProjects\MePhC-Windows\.test_copy && C:\Users\icywo\AppData\Local\Programs\Python\Python312\python.exe -m pytest -q C:\Users\icywo\PycharmProjects\MePhC-Windows\.test_copy\tests\<test-file>.py"
```

Use a unique temporary directory if an old copy is locked. Remove only the exact temporary directory after verification. The full legacy test collection also imports pre-existing `meep` and `shapely`, which are absent from the available Windows Python; report that as an environment limitation instead of treating it as an E2 or pure-data failure. Always still run focused tests, `python3 -m compileall -q mephc tests`, and `git diff --check`.

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

