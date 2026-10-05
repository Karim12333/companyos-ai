# Approvals

Human control is enforced in code by the **policy engine** (`companyos/tools/policy.py`), a pure function
the tool gateway evaluates before any tool runs.

## Risk levels

| Level | Examples | Behavior |
|---|---|---|
| 1 Autonomous | search, read, draft, internal artifacts | Allowed |
| 2 Controlled | scheduled drafts, branches, pull requests, non-production changes | Organization `approval_policies` (default: requires approval) |
| 3 Human approval | publish, external email, spending, production deploys, deletions | **Always** requires CEO approval |

## Decision order

1. Unknown tool: deny
2. Agent inactive: deny
3. Tool not granted to the agent: deny
4. Explicit agent permission `deny`: deny
5. Level 3 while the objective blocks external actions: deny
6. Objective or daily budget exhausted: deny
7. Level 3: require approval (no setting can relax this)
8. Agent permission `require_approval`: require approval
9. Level 2: organization policy
10. Otherwise: allow

Every decision is written to `audit_logs`.

## Lifecycle

1. The gateway validates the arguments, freezes them in an `approvals` row, and creates a CEO Inbox item
   (`APPROVAL_REQUIRED`) and an activity event. The agent is told not to retry.
2. The task moves to `WAITING_FOR_APPROVAL` and the CEO receives an email with a deep link.
3. An owner or admin approves or rejects from the Inbox, the objective page or the approval page.
4. The API records and audits the decision, then signals the workflow.
5. On approval, the gateway re-checks the non-approval rules and executes **exactly the frozen arguments**;
   the outcome is stored in `execution_result`. On rejection nothing is executed.
6. Decisions are final; a second decision returns `409`.

Per objective, the CEO chooses "Allowed with my approval" (default) or "Blocked entirely" for external actions.
