# MePhC Thin Flow

## Direct local interactive mode

When the user explicitly starts local work from VS Code, `studio.py`, or a
Python file, treat it as direct interactive development. Use the pinned Conda
`mp` interpreter and the canonical editable source in this Windows sandbox.
Do not invoke Thin Flow, Courier, or Luna unless the user explicitly asks to
enter the automatic workflow. Local preview, calculation, plotting, testing,
and debugging need no relay approval.

## Workspace invariants

`C:\Users\icywo\PycharmProjects\MePhC-Windows` on local branch `sandbox` is
the only editable MePhC source. Push only `origin/sandbox`. Never move
`origin/main`; its accepted baseline is
`5a4e9e839eff40f582c2404ff3eadd2bf8b676b5`.

WSL is execution-only. Exact commits below
`/home/icy/.cache/mephc-runner/checkouts/<sha>` are detached and read-only.

## Normal autonomous loop

Use these four commands for ordinary work:

```text
mephc-flow.cmd status
mephc-flow.cmd resume
mephc-flow.cmd execute
mephc-flow.cmd closeout
```

Follow the returned `state` and `safe_next`:

```text
AWAITING_WORK_ORDER -> resume
READY             -> edit as needed in this MePhC sandbox, then execute
RUNNING           -> execute only to reconcile the same durable run
READY_TO_CLOSE    -> closeout
AWAITING_REPLY    -> closeout
TERMINATED        -> notify the fixed supervisor, then stop
HARD_BLOCKED      -> bounded self-repair, then supervisor escalation
```

Continue automatically until Chat terminates the workflow. Starting or
continuing the workflow is standing authorization for its fixed Courier
closeout; never ask the user for per-report approval.

Before ending any Luna turn or becoming idle for any reason, including normal
completion, a milestone, `TERMINATED`, `HARD_BLOCKED`, or the absence of a
`safe_next`, send one structured handoff to the fixed supervisor task. The supervisor decides whether stopping is legitimate. A milestone is never by
itself permission to stop. Use the stable identity
`MEPHC-IDLE-HANDOFF:<work-order-id-or-null>:<state>` and include the current
work order, state, safe next action, source SHA, durable job/request/run IDs,
actual counts, scientific progress, and the proposed reason for becoming
idle. After successful delivery, remain idle until the supervisor responds.
Do not create or fork another task. A definite task-message transport failure
may be retried once; only a second failure may be reported to the user.

The semantic hierarchy is fixed: Project -> Goal -> Milestone/Branch -> Work
Order -> Job/Run. A `STOP_*` scientific decision, negative result, milestone,
job terminal state, work-order closeout, or Goal closure never terminates the
Project workflow. Chat must issue a substantive successor, including the next
project-level Goal when the current Goal closes. `WORKFLOW_TERMINATED=true` is
only a project-level termination proposal and maps to
`HARD_BLOCKED / TERMINATION_REVIEW_REQUIRED` until this supervisor approves it.
`TERMINATED` is only valid after that approval and is not evidence that the
scientific goal succeeded or became impossible. A terminal proposal handoff must also
contain this compact termination review:

```text
GOAL_OUTCOME=<SUCCEEDED|BLOCKED|CONTRADICTED>
COMPLETION_EVIDENCE=<direct evidence for the claimed outcome>
ATTEMPTS_COMPLETED=<scientific attempts and results, not routine bookkeeping>
UNRESOLVED_QUESTIONS=<remaining scientific uncertainties>
ALTERNATIVE_EXPLANATIONS=<plausible competing causes>
CHEAPEST_NEXT_TEST=<least-cost discriminating test, or NONE with reason>
COUNTEREVIDENCE_SEARCH=<what was checked that could falsify stopping>
WHY_STOP_IS_SUFFICIENT=<why no useful authorized continuation remains>
```

The supervisor must independently challenge the proposed termination before
approving idle. Check the original goal and completion criteria, inspect the
decisive numerical result rather than only `state`, and look for at least one
plausible alternative explanation or cheaper discriminating test. Reject the
termination and resume the same Luna when the conclusion depends on an
untested convention, representation, gauge, coordinate transform, parser, or
other model assumption. Approve a blocked stop only when the report shows
that bounded attempts were made, remaining alternatives were considered, and
no safe useful next action exists. For success, verify the stated completion
evidence. Never describe a negative result as final merely because Chat or
Thin Flow returned `TERMINATED`.

The returned state is authoritative. Never escalate while the flow reports
`READY`: `READY` with no job/run proves expensive work was not started, even
if an earlier `execute` client call was interrupted, so invoke `execute` again.
A missing contract-declared file, a missing test, or `TESTS_FAILED` is ordinary
implementation work; repair it locally and execute again. Do not reinterpret
these cases as uncertain Native side effects.

Before `execute`, inspect the current contract's tracked entrypoint and tests.
If either is missing, implement it in this sandbox first. An
`ENTRYPOINT_IMPLEMENTATION_REQUIRED`, `TEST_IMPLEMENTATION_REQUIRED`, or
`TESTS_FAILED` response remains `READY`: repair once and invoke `execute`
again. Never close out or escalate that local implementation state.

## Risk-based autonomy

Hard invariants are limited to work-order/request/run identity, Git SHA and
unchanged main, explicit Native/provider/solver budgets, dataset hashes, and
unique reconciliation of expensive side effects. Chat wording, kind/action,
capability names, null spelling, output-field layout and Courier envelopes are
soft inputs: normalize them, record warnings and continue with the least
privileged interpretation.

`allowed_writes` is advisory. You may edit any necessary file inside this
MePhC sandbox, including Thin Flow and this file; report the actual diff. Do
not touch another project. Missing or ambiguous Native authorization means
zero Native, not a guessed execution.

Low-cost verification may repeat once: status, capture, tests, fetch and a
same-SHA push. Courier may resend one semantically equivalent compact report
under the same logical request. Never blindly repeat Native, provider, solver
or an uncertain write; query the original durable ID.

## Self-maintenance and escalation

For unclear scientific goals, budgets or conclusions, close out a zero-side-
effect clarification result so Chat can issue a corrected successor contract.
If Chat returns `LOCAL_SUPERVISOR_REQUIRED=true`, the remote reviewer has
declared that decisive evidence is unavailable in remote Git. Thin Flow maps
that receipt to `HARD_BLOCKED / LOCAL_SUPERVISOR_REQUIRED`. Escalate it
directly to the fixed supervisor with the original work-order/request/job/run
IDs and actual counts. Do not close out again, create a clarification or
corrective work order, resend Courier, rerun science, or ask the user.
For a local parser, test, Git, permission or Thin Flow defect:

1. diagnose the exact failure without rerunning scientific work;
2. make one convergent framework repair in this sandbox;
3. run the fixed infrastructure tests and push `origin/sandbox`;
4. resume the original work order and durable IDs.

The repair must remove or soften a gate, not add a service, command, state,
certificate or work-order-specific branch. Escalate a repeated local failure
after one repair only when Thin Flow returns `HARD_BLOCKED`, or reports
`RUNNING` with `side_effect_state=UNKNOWN`. Do not escalate a `READY` local
implementation or test failure. The fixed supervisor task is
`01a04136-7e60-75c3-88cf-156581a3733e` on host `local`. The only Luna worker is
`01a0480e-b79d-75c3-ac80-5db601b32d67`; never create or fork another worker.

Use `send_message_to_thread` with:

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

Retry a definite task-message transport failure once. After delivery, remain
idle. Only the supervisor contacts the user for Desktop restart, login/target
failure, destructive action, main promotion, irreconcilable side effects or a
genuine user choice.

## Execute and closeout

`execute` commits current MePhC changes, records any difference from Chat's
advisory file list, tests the exact checkout, verifies dataset hashes, pushes
sandbox and runs at most the explicit budget. Entrypoints receive only
`MEPHC_INPUT_BUNDLE` and `MEPHC_RESULT_PATH`; they do not scan durable state.

`closeout` captures the first complete post-submission reply, closes the Chat
window, then parses offline. A wrong or missing envelope is a warning when the
chronologically matched reply contains a successor work-order ID. A response
format or safety-filter failure permits one equivalent compact resend under
the same request. It never reruns science.

The zero-argument closeout uses adaptive milestone Query preferences. Ordinary
science requests `hard + detailed + milestone`; corrective, diagnostic or
recertification work requests `challenge + manual_book + milestone`, asking
Chat to combine local implementation, tests and recertification with the next
substantive objective. When a different span is genuinely useful, the same
`closeout` command may use only these optional preference flags:

```text
--task-difficulty normal|hard|challenge|adaptive
--instruction-level normal|detailed|manual_book|adaptive
--report-policy adaptive|per-work-order|milestone|final-only
```

They affect only the next Query's difficulty, detail and requested span. They
cannot change its report body, request ID, Chat target, budget or transport.

Completion provenance remains:

```text
CODE_CHANGE=NONE|SANDBOX_ONLY
BASE_MAIN_SHA=<sha>
SANDBOX_HEAD_SHA=<sha>
AUDIT_DIFF_RANGE=<base>..<sandbox-head>
```
