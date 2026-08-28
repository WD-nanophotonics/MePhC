# MePhC direct relay workflow

## Canonical workspace

`C:\Users\icywo\PycharmProjects\MePhC-Windows` on local branch `sandbox` is
the only editable MePhC source tree. `origin/main` is the immutable accepted
baseline. Ordinary work may fast-forward only `origin/sandbox`.

WSL is an execution environment. Exact committed source is materialized in a
detached clean checkout below `/home/icy/.cache/mephc-runner/checkouts/<sha>`.
Do not edit those checkouts. TriLatt, SqrLatt, and another work-order-named WSL
project remain independently editable downstream projects.

## Startup and continuation

At task start run `mephc-flow.cmd status`, then `mephc-flow.cmd resume`. Read
the receipt-bound active Chat work order and continue it directly. Do not call
the retired `mephc_*` MCP tools, doctor, prelive, runtime activation, broker,
worker, certificates, or durable change jobs.

Authority precedence is:

1. Current user instructions and constraints.
2. The receipt-bound active Chat work order.
3. This project policy and `mephc-flow` defaults.

Do not ask the user to paste relay prompts or responses. An empty local queue
does not mean the workflow is complete.

## Editing, testing, and publication

Agents edit the Windows `sandbox` worktree directly using normal repository
tools. Keep changes within the active work order and preserve unrelated user
changes. Scientific conclusion-producing code and compact evidence must be
committed and published for audit.

Use:

```text
mephc-flow.cmd publish --tests tests/<solver-free-test>.py [...]
```

This command requires a clean committed `sandbox`, verifies the fixed
`origin/main`, runs the declared tests in the exact ext4 SHA checkout, and
fast-forwards `origin/sandbox`. It has no certificate, prelive, installed-build
or activation dependency. Never push or promote `main` without a separate,
explicit user authorization. The repository pre-push hook rejects `main` and
non-sandbox pushes.

For ordinary WSL work, `mephc-runtime sync|path|run` uses the current clean
committed sandbox while keeping outputs in the downstream project.

## Native execution

Native/MPB execution is permitted only when the current receipt-bound Chat
work order explicitly authorizes it and declares a numeric budget. Invoke:

```text
mephc-flow.cmd run-native --work-order <id> --cost <n> --project <allowed-path> -- <argv...>
```

Arguments are passed as an array in the fixed WSL/Conda environment. The
project must be the exact SHA checkout or an exact path named by the work
order. A user-supplied session cap may only reduce the Chat budget.

If the caller is interrupted, use `mephc-flow.cmd native-status <run-id>`.
Never infer from a missing foreground process and never resubmit an uncertain
native run. The same payload reuses its durable run record.

## Courier reporting

Reporting policy is configurable with:

```text
mephc-flow.cmd start --report-policy adaptive|per-work-order|milestone|final-only [--native-cap N]
```

Precedence is user session choice, then work-order declaration, then the
default `adaptive` policy.

Create a report only with:

```text
mephc-flow.cmd report --work-order <id> --kind milestone|complete|blocked --message-file <utf8-file>
```

The request ID is deterministic. If the request exists or may have been
submitted, use only:

```text
mephc-flow.cmd courier-reconcile --request-id <existing-id>
```

Recovery reuses the immutable request and never resends the user turn. Continue
until a matching receipt-bound response is available or a hard Chat/login/
target error occurs. Do not use Browser, Chrome, Gmail, another Chat profile,
another request ID, or another transport.

## Safety boundaries

- Do not modify unrelated projects, arbitrary user directories, browser
  profiles, accounts, or arbitrary processes.
- Do not create a second Luna worker or parallelize the same work order.
- Do not recreate the retired Runner or add new certificate/permission layers.
- Preserve the legacy outbox, receipts, responses, workflow ledger, and
  retirement archives.
- A transport or native side effect whose state cannot be uniquely reconciled
  requires a human decision; it never authorizes a retry.

Completion reports involving auditable code include:

```text
CODE_CHANGE=NONE|SANDBOX_ONLY|SANDBOX_AND_AUTHORIZED_MAIN_PROMOTION
BASE_MAIN_SHA=<sha>
SANDBOX_HEAD_SHA=<sha>
AUDIT_DIFF_RANGE=<base>..<sandbox-head>
```
