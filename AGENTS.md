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
