# MePhC Thin Flow

## Workspace

`C:\Users\icywo\PycharmProjects\MePhC-Windows` on local branch `sandbox` is
the only editable MePhC source. Ordinary work may fast-forward only
`origin/sandbox`. Never move `origin/main`, whose accepted baseline is
`5a4e9e839eff40f582c2404ff3eadd2bf8b676b5`.

WSL is execution-only. Exact commits are materialized as clean detached ext4
checkouts below `/home/icy/.cache/mephc-runner/checkouts/<sha>`; never edit them.

## The complete Agent loop

Use only these commands:

```text
mephc-flow.cmd status
mephc-flow.cmd resume
mephc-flow.cmd execute
mephc-flow.cmd closeout
```

The states and their only legal actions are:

```text
AWAITING_WORK_ORDER -> resume
READY             -> edit only contract allowed_writes, then execute
RUNNING           -> execute (reconcile the same durable run; never resubmit)
READY_TO_CLOSE    -> closeout
AWAITING_REPLY    -> closeout
TERMINATED        -> stop
HARD_BLOCKED      -> escalate to the fixed supervisor task
```

Always follow the returned `state` and `safe_next`. Current user instructions
override workflow defaults. Continue `closeout -> resume -> execute -> closeout`
until Chat explicitly terminates or the flow exhausts its bounded recovery.
Do not stop on the first ordinary UI, transport, permission or parsing error:
read-only checks may repeat, verifiable Git/test operations may retry once, and
`closeout` owns one automatic same-request Courier resend. Native/provider/
solver work is never blindly repeated; reconcile its durable ID instead.

## Automatic supervisor escalation

The fixed high-capability supervisor task is
`01a04136-7e60-75c3-88cf-156581a3733e` on host `local`. The only Luna worker
is `01a0480e-b79d-75c3-ac80-5db601b32d67`.
Do not create, fork, or wake any other worker or supervisor.

Escalate only after bounded local diagnosis when one of these is true:

- Thin Flow remains `HARD_BLOCKED` after its built-in recovery;
- the unique `safe_next` cannot run because of a tool, approval, or environment
  failure;
- a Native or Courier side effect cannot be uniquely reconciled; or
- the same framework failure recurs after one verified recovery attempt.

Do not escalate a scientific negative result, a valid solver-free fail-closed,
`READY_TO_CLOSE`, normal Courier waiting, or `TERMINATED`.

Use the Codex `send_message_to_thread` tool to send the supervisor one concise
structured message. Do not use Courier or add a flow command for escalation.
The message must contain these exact fields:

```text
ESCALATION_ID=MEPHC-ESCALATION:<work-order-id>:<failure-code>
SOURCE_TASK_ID=01a0480e-b79d-75c3-ac80-5db601b32d67
WORK_ORDER_ID=<id-or-null>
STATE=<state>
FAILURE_CODE=<structured-code>
SOURCE_SHA=<sha-or-null>
JOB_ID=<id-or-null>
REQUEST_ID=<id-or-null>
NATIVE_RUN_ID=<id-or-null>
ACTUAL_COUNTS=<native/provider/solver/dataset>
RECOVERY_ATTEMPTED=<bounded-actions>
UNCERTAIN_SIDE_EFFECT=<true|false>
REQUESTED_SUPERVISOR_ACTION=<diagnose-and-resume|reconcile|framework-fix>
```

Send to the fixed supervisor task with `hostId=local`. If the task-message call
returns a definite transport failure, retry the identical message once. After
successful delivery, end the Luna turn and remain idle: do not modify files,
retry work, ask the user, or create another task. If the second delivery attempt
also fails definitively, report only that task-to-task communication hard error
to the user and stop.

When the supervisor later sends a continuation, re-read `AGENTS.md`, run bounded
`status`, and follow the existing work order and original durable IDs. Never
replace an uncertain Native run or Courier request.

## Execute semantics

The receipt-bound `mephc-science-work-order-v1` contract owns action, source,
entrypoint, budgets, tests, inputs, allowed writes and output schemas.

`execute` performs one bounded transaction:

1. reject out-of-contract worktree changes;
2. create one scoped commit when needed;
3. run the contract tests in an exact checkout;
4. fast-forward `origin/sandbox` after confirming `main` is unchanged;
5. verify every historical dataset record;
6. run the fixed zero-argument entrypoint only if all checks passed.

Historical inputs use only:

```json
{"dataset_id":"<sha256>","manifest_sha256":"<sha256>","record_key_sha256":"<sha256>"}
```

The framework provides verified payloads through `MEPHC_INPUT_BUNDLE` and the
fixed result location through `MEPHC_RESULT_PATH`. Scientific entrypoints must
not search durable state, rebuild dataset namespaces, inspect arbitrary paths,
or bind themselves to their containing final commit.

A failed input check is a normal solver-free blocked result. Do not repair the
framework, retry Native, or create a second job.

## Closeout semantics

`closeout` derives complete/blocked status mechanically from the terminal job.
One work order has exactly one deterministic Courier request. It first performs
normal recovery, then one exact user-turn-anchored read-only capture. A missing
or wrong reply envelope is only an offline warning when the post-submission
reply contains a valid successor contract. If recovery still fails, `closeout`
may resend the same immutable report once under the same request ID. Total
submission count is capped at two; it can never create a replacement request
or rerun scientific work. Only exhaustion of this ladder is hard-blocking.

The user's instruction to start or continue this workflow is standing
authorization for the fixed receipt-bound closeout. Invoke the zero-argument
`mephc-closeout.cmd` launcher directly. Do not request another confirmation,
describe it as a new external-message decision, or stop at `READY_TO_CLOSE`.
The launcher rejects every argument and cannot select message text, a request,
a destination, a profile, or a transport.

Do not use Browser, Chrome, Gmail, another profile, another request, or another
transport. Escalate login, target, validation, transport, destructive-action,
`main`-promotion, or genuine user-choice blockers to the fixed supervisor
first; only the supervisor decides whether the user must be contacted.

## Boundaries

- Do not use archived flow modules, retired MCP/Runner/broker/certificates, or
  old commands such as `science-preflight`, `run-native`, `report`,
  `closeout-blocked`, `courier-reconcile`, or `supervision-*`.
- Do not scan WSL or durable state. `status` is the complete bounded view.
- Do not create a second worker or parallelize one work order.
- Native/MPB execution requires the current machine contract and budget.
- Preserve unrelated user changes and other projects.

Completion provenance remains:

```text
CODE_CHANGE=NONE|SANDBOX_ONLY
BASE_MAIN_SHA=<sha>
SANDBOX_HEAD_SHA=<sha>
AUDIT_DIFF_RANGE=<base>..<sandbox-head>
```
