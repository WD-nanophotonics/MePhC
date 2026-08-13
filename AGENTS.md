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

