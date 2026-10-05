# Data Model

PostgreSQL 16 + pgvector. UUID primary keys, `created_at` / `updated_at` timestamps (UTC).
Every tenant-owned table carries `organization_id` and is protected by Row Level Security
(see `MULTITENANCY.md`). JSONB is used only for extensible metadata, never for core relationships.

## Global tables (not tenant-scoped)

| Table | Purpose |
|---|---|
| `users` | Identity: email, name, password hash (argon2), `is_platform_admin`, active flag |
| `user_sessions` | Server-side sessions (hashed token, expiry, revocation) |
| `organizations` | Tenant root: name, slug, template, status |

## Tenant tables

### Organization & access
| Table | Key columns |
|---|---|
| `organization_members` | user, role (`owner` / `admin` / `member` / `viewer`) |
| `organization_settings` | default/premium model, budgets, max iterations, concurrency, notification emails |
| `organization_preferences` | promoted feedback (scope: organization / department / agent) |

RBAC roles map to permissions in code (`companyos/auth/rbac.py`). Roles are a fixed, small set in V1;
a `roles` / `permissions` table can be introduced when custom roles are needed.

### Organization structure
| Table | Key columns |
|---|---|
| `departments` | name, slug, description, manager agent, parent department, sort order |
| `agents` | name, role key, title, department, manager (reports-to), instructions, goals, responsibilities, model, limits, status, active, memory config |
| `agent_relationships` | agent → related agent, kind (`can_delegate_to`) |
| `agent_tools` | agent → tool key, enabled, config |
| `agent_permissions` | agent → action key, effect (`allow` / `require_approval` / `deny`) |

Agent templates live in versioned code (`companyos/templates`) and are instantiated into these tables.

### Work
| Table | Key columns |
|---|---|
| `projects` | name, description, status, dates |
| `objectives` | project, creator, title, instruction, context, status, priority, target date, stage, progress, coordinator agent, workflow id, budget, approval policy, executive summary, cost |
| `tasks` | objective, project, parent task, assigned agent, role key, plan key, title, instructions, status, priority, retries, expected output, acceptance criteria, review/approval flags, result, error category/message, recoverable |
| `task_dependencies` | task → depends-on task (DAG edge) |
| `task_runs` | one row per execution attempt: agent, attempt, status, tokens, cost, trace, error |
| `workflow_runs` | Temporal workflow id / run id per objective execution |
| `agent_messages` | objective, task, sender, recipient, kind, subject, body, reason |
| `activity_events` | human-readable timeline (objective / project / department / agent / task scoped) |

### Output & control
| Table | Key columns |
|---|---|
| `artifacts` | objective, project, task, producing agent, title, kind, MIME, current version, review/approval status |
| `artifact_versions` | version, storage key, size, SHA-256 checksum, preview text |
| `approvals` | action key, risk level, payload, status, decided by/at, note, execution result |
| `approval_policies` | organization overrides per action key (Level 2 decisions) |
| `inbox_items` | category, severity, links to objective/agent/approval/artifact/task, read, action required |
| `notifications` | outbound email log: kind, recipient, subject, status, provider id, error |
| `agent_feedback` | CEO feedback on outputs; can be promoted into preferences |

### Knowledge
| Table | Key columns |
|---|---|
| `company_memory` | structured facts: category (identity, mission, brand, policy, product, business rule) |
| `documents` | long-form documents (title, source, content, project) |
| `document_chunks` | chunk text + `embedding vector(1536)` (HNSW cosine index) |

Embeddings are stored on `document_chunks` directly; a separate `embeddings` table adds no value
while there is one embedding per chunk.

### Integrations, usage & audit
| Table | Key columns |
|---|---|
| `integrations` | provider key, enabled, status, scopes, non-secret config, health, last sync |
| `integration_credentials` | **encrypted** secret (Fernet ciphertext), key version, last 4 chars |
| `model_usage` | provider, model, purpose, tokens in/out, estimated cost, latency, agent/task/objective links |
| `audit_logs` | actor (user/agent/system), action, target, outcome, details, correlation id |

`model_usage` is the cost ledger (cost events). Aggregations power Analytics and budget checks.

## Status enums

- **Objective:** `DRAFT, PLANNING, RUNNING, WAITING, WAITING_FOR_APPROVAL, REVIEWING, COMPLETED, COMPLETED_WITH_ISSUES, FAILED, CANCELLED`
- **Task:** `QUEUED, READY, RUNNING, BLOCKED, REVIEW, WAITING_FOR_APPROVAL, COMPLETED, FAILED, CANCELLED`
- **Approval:** `PENDING, APPROVED, REJECTED, EXPIRED, CANCELLED`

## Soft deletion

Only agents (`is_active`) and departments (archived via agents) use soft deactivation, because history
must keep pointing at them. Work records are never deleted by the application.
