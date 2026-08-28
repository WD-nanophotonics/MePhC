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

At task start run `mephc-flow.cmd status`, then `mephc-flow.cmd resume`, then
`mephc-flow.cmd science-preflight` for a scientific work order. Continue only
when the receipt-bound `mephc-science-work-order-v1` contract validates and
preflight returns `ready_to_run=true`. Do not infer a science state machine
from the surrounding prose. Do not call
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

## Scientific execution

Normal scientific work uses only the fixed actions:

```text
mephc-flow.cmd science-selftest
mephc-flow.cmd science-preflight
mephc-flow.cmd science-acquire
mephc-flow.cmd science-status <job-id>
mephc-flow.cmd dataset-verify <dataset-id>
mephc-flow.cmd science-analyze
```

The machine contract owns the exact source, tracked zero-argument entrypoint,
project, capabilities, budgets, dataset inputs, output schemas, allowed writes,
acceptance criteria, and forbidden operations. Agents do not supply a command,
path, provider factory, storage root, codec, or result channel. Missing or
invalid contracts stop before creating a job.

`run-native -- <argv>` is a maintenance compatibility interface and is not part
of the low-reasoning Agent workflow.

If the caller is interrupted, use `science-status` for the same deterministic
job ID. Never infer from a missing foreground process and never resubmit an
uncertain scientific job. A completed immutable dataset makes every later
recovery solver-free.

SCIENCE work orders cannot modify `tools/mephc-flow`; INFRASTRUCTURE work
orders cannot advance scientific conclusions. Two consecutive infrastructure
repairs for one scientific milestone set `WORKFLOW_OVERHEAD_EXCESSIVE=true`
and require one convergent framework repair instead of more local patches.

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
