# MePhC direct workflow

`mephc-flow` is the single Agent-facing workflow helper. It records durable
state and enforces project scope, but it does not install or attest a second
copy of the repository.

The normal sequence is:

1. `mephc-flow start` and `mephc-flow resume`.
2. Edit and commit the Windows `sandbox` branch directly.
3. `mephc-flow publish --tests tests/...py`.
4. Use `run-native` only when the active Chat work order explicitly authorizes
   native execution and declares a budget.
5. Use no-argument `closeout`; it creates or reconciles one deterministic
   canonical report, consumes the reply, and returns the next work order.

Low-reasoning Agents never compose an outbound message or select a Courier
target. `closeout-blocked --code UPPERCASE_CODE` is the only normal blocked
report path. The legacy `report --message-file` command is maintenance-only.

All WSL subprocesses are consoleless, receive argv as an array, and run from
an exact detached ext4 checkout. `origin/main` is immutable.

`mephc-runtime sync|path|run` remains available for both humans and Agents. It
is now part of this direct workflow rather than an installed Runner build.
