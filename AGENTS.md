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
HARD_BLOCKED      -> ask the user
```

Always follow the returned `state` and `safe_next`. Current user instructions
override workflow defaults. Continue `closeout -> resume -> execute -> closeout`
until Chat explicitly terminates or the flow exhausts its bounded recovery.
Do not stop on the first ordinary UI, transport, permission or parsing error:
read-only checks may repeat, verifiable Git/test operations may retry once, and
`closeout` owns one automatic same-request Courier resend. Native/provider/
solver work is never blindly repeated; reconcile its durable ID instead.

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
transport. Only login, target, validation, or transport hard errors require the
user.

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
