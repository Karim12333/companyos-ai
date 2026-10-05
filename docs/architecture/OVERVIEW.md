# Architecture Overview

CompanyOS is a **modular monolith** (FastAPI) plus **durable workers** (Temporal), with a Next.js web
client. All components share one Python domain package so boundaries stay clean without network hops.

```
                ┌──────────────────────────┐
  Browser ─────►│  apps/web  (Next.js)     │
                └────────────┬─────────────┘
                             │ HTTPS (JSON, cookie session + CSRF header)
                             │ SSE  (live activity)
                ┌────────────▼─────────────┐        ┌─────────────────────┐
                │  apps/api  (FastAPI)     │───────►│ Temporal server     │
                │  companyos.api           │ start/ │ (durable workflows) │
                │  companyos.services      │ signal └─────────┬───────────┘
                │  companyos.domain        │                  │ task queue
                └──┬──────────┬─────────┬──┘        ┌─────────▼───────────┐
                   │          │         │           │ worker              │
                   │          │         │           │ companyos.worker    │
                   │          │         │           │  • ObjectiveWorkflow│
                   │          │         │           │  • activities       │
                   │          │         │           │  • agent runtime    │
                   │          │         │           │    (LangGraph)      │
                   │          │         │           │  • tool gateway     │
                   │          │         │           └──┬───────┬───────┬──┘
           ┌───────▼──┐  ┌────▼───┐ ┌───▼────┐         │       │       │
           │PostgreSQL│  │ Redis  │ │ MinIO  │◄────────┘       │       │
           │+ pgvector│  │ pub/sub│ │ (S3)   │                 │       │
           │ + RLS    │  │ limits │ └────────┘          LLM provider   Email
           └──────────┘  └────────┘                    (per-tenant)   (SMTP/Resend)
```

## Components

| Component | Responsibility |
|---|---|
| `apps/web` | Next.js App Router UI: Headquarters, Inbox, Objectives, Departments, Agents, … |
| `apps/api/companyos/api` | HTTP routes, auth dependencies, request context, SSE stream |
| `apps/api/companyos/services` | Business logic (objectives, approvals, artifacts, knowledge, …) |
| `apps/api/companyos/db` | SQLAlchemy models, session management, tenant context (RLS) |
| `apps/api/companyos/agents` | Agent runtime (LangGraph), planner, reviewer, reporter, prompts |
| `apps/api/companyos/tools` | Tool registry, **tool gateway**, **policy engine** |
| `apps/api/companyos/workflows` | Temporal workflow definitions + activities |
| `apps/api/companyos/providers` | LLM, embeddings, email, storage, web search abstractions |
| `apps/api/companyos/templates` | Organization templates (Software / AI Company) |
| `apps/api/companyos/worker.py` | Temporal worker entrypoint |

## Key decisions (see `docs/adr`)

- ADR-0001 Modular monolith + durable workers sharing one domain package.
- ADR-0002 Temporal for durability, LangGraph for agent reasoning.
- ADR-0003 Tenant isolation: `organization_id` everywhere + PostgreSQL RLS + app checks.
- ADR-0004 Server-Sent Events for realtime.
- ADR-0005 Local session auth behind a provider abstraction; cookie + CSRF header.
- ADR-0006 Per-tenant AI provider credentials encrypted with an envelope master key.
- ADR-0007 Offline mock LLM provider for development, tests and demos.

## Request lifecycle

1. Request arrives → correlation ID assigned (`X-Correlation-Id`), structured log context bound.
2. Session cookie resolved to a user; for `/orgs/{org_id}/…` routes membership + role checked.
3. A DB transaction is opened with `app.org_id` / `app.user_id` set (`SET LOCAL`), so RLS applies.
4. Service performs work, writes activity events / audit logs; events are published to Redis.
5. SSE subscribers for that organization receive events and the UI refreshes affected queries.

## Objective lifecycle (summary)

`DRAFT → PLANNING → RUNNING ⇄ WAITING_FOR_APPROVAL → REVIEWING → COMPLETED | COMPLETED_WITH_ISSUES | FAILED | CANCELLED`

See `WORKFLOWS.md` for the complete execution model.

## Observability

- JSON structured logs (`structlog`) with `correlation_id`, `organization_id`, `objective_id`,
  `workflow_id`, `task_id`, `task_run_id` bound where known.
- Secrets redacted by a log processor.
- `/health/live` and `/health/ready` (checks DB, Redis, Temporal).
- Errors are persisted on tasks / task runs / workflow runs and surfaced in UI and reports.
- Error-tracking integration point (`companyos.observability.report_exception`) for Sentry-like tools.
