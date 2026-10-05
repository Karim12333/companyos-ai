# Workflows

## Objective workflow (`companyos/workflows/objective_workflow.py`)

One Temporal workflow per objective run (`objective-{id}`; resumed runs `objective-{id}-r{n}`).

```
start_objective
plan_objective ──(fails)────────────────────────────────┐
loop:                                                    │
  wait while paused                                      │
  get_ready_tasks   (PostgreSQL is the source of truth)  │
  start up to max_parallel task pipelines                │
  wait until a pipeline finishes, a signal, or cancel    │
finalize_objective (status + executive report) ◄────────┘
notify_objective_outcome (email)
```

### Task pipeline (one per task, concurrent)

```
execute_task ──failed──► stop (task FAILED; dependents BLOCKED on the next scan)
  │ approvals requested?
  ├─► notify_approvals → wait for approval_decided signals (DB reconciliation every 10 min)
  │   → resolve_task_approvals (gateway executes approved actions, records rejections)
  │ review required?
  ├─► review_task ──revise──► execute_task again (bounded by max_review_revisions)
  └─► complete_task → handoff messages to dependent agents
```

### Signals and queries

| Signal | Effect |
|---|---|
| `approval_decided(approval_id)` | Unblocks the waiting task pipeline |
| `pause` / `resume` | Stops or resumes scheduling new tasks |
| `cancel` | Cancels running pipelines; remaining tasks and pending approvals become CANCELLED |
| `wake` | Re-scan the DAG (for example after a retry) |

The `state` query returns the stage, paused and cancelled flags and running task ids.

## Durability

- Workflow state lives in Temporal; task state lives in PostgreSQL. Restarting the API or worker, closing
  the browser or losing the network does not lose progress: the workflow resumes from its history and asks
  the database which tasks are ready.
- Activities are safe to re-run: `plan_objective` returns existing tasks, `complete_task` ignores completed
  tasks, `finalize_objective` returns an existing report.
- Retrying a failed task after the objective finished starts a new run with `resume=True`, which skips
  planning and continues the DAG.

## Retries and failures

| Situation | Handling |
|---|---|
| Provider rate limit or timeout | Temporal retry (3 attempts, exponential backoff); `task.retry_count` updated |
| Non-recoverable provider error, budget exhausted | Task FAILED with its category; no retry |
| Unexpected error after the final attempt | Task FAILED (internal) via `mark_task_failed` |
| Dependency failed | Dependents BLOCKED (category `dependency`, recoverable) |
| Planning failed | Objective FAILED; the report explains why |

Final status: `COMPLETED` (no failures), `COMPLETED_WITH_ISSUES` (some failed or blocked work),
`FAILED` (nothing completed or planning failed), `CANCELLED`.

Every failure creates an inbox item and an activity event, and appears in the executive report with its
category, message and whether it can be retried. Nothing is swallowed silently.
