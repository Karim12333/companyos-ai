# V1 Scope

## Definition of done

V1 is successful when a user can:

1. Open the CompanyOS web application.
2. Sign in.
3. Create / select an organization.
4. See a professional CEO Headquarters dashboard backed by real data.
5. See departments and agents.
6. Create a new Objective in natural language.
7. Have the Chief of Staff generate a persisted plan.
8. See tasks and dependencies.
9. Watch multiple agents execute eligible work in parallel.
10. See communication / activity between agents.
11. Receive generated artifacts.
12. Have outputs pass through review.
13. See high-risk actions stopped at human approval.
14. Approve / reject items from the CEO Inbox.
15. Receive a final executive report.
16. Receive an internal email notification on completion.
17. Close the browser while processing and return later without losing the workflow.
18. See failures clearly.
19. Create another organization whose data is isolated from the first.
20. Have tests proving core tenant isolation.

## In scope

- Local email/password auth behind an auth-provider abstraction; httpOnly session cookie + CSRF token.
- Organizations, memberships, RBAC (owner / admin / member / viewer) and platform admin flag.
- PostgreSQL Row Level Security on every tenant table plus application-layer checks.
- Software / AI Company template (one high-quality template, extensible registry).
- Departments, agents, reporting lines, delegation rights, tool permissions — all data-driven.
- Objectives → Chief of Staff planning (LangGraph) → persisted task DAG.
- Temporal workflow per objective: parallel execution of ready tasks, review loop, approvals via
  signals, pause / resume / cancel / retry, executive report, notification.
- Agent runtime (LangGraph) with a **tool gateway** + **policy engine** enforcing permissions, risk
  levels, approval requirements and budgets.
- Tools: company knowledge search, artifact creation, delegation, messaging, web search
  (if a provider is configured), mock social publishing (Level 3, approval required).
- Artifacts with versions stored in S3-compatible storage (MinIO locally).
- CEO Inbox, Approvals, Activity feed (realtime via SSE), Headquarters, Objective / Department /
  Agent / Project / Artifact pages, Knowledge (documents + pgvector search, preferences), Integrations,
  Analytics (usage / cost), Settings (members, AI provider, budgets, approval policies), Platform Admin.
- Per-organization AI provider configuration (OpenAI-compatible) with encrypted API key storage.
  Offline deterministic mock model when no key is configured.
- Email notifications (dev SMTP → Mailpit, Resend provider for real delivery).
- Model usage and cost tracking, budget enforcement, concurrency limits.
- Tests: unit, service, authorization, tenant isolation, workflow, API; Vitest; Playwright E2E.
- Docker Compose for local stack; GitHub Actions CI.

## Out of scope for V1

- Drag-and-drop Organization Designer (data model supports it; V1 has a read-only org chart and
  form-based editing).
- Real third-party integrations beyond AI provider, Resend and web search (GitHub, Gmail, Slack, … later).
- Binary office formats (pptx / xlsx / pdf generation). V1 artifacts are Markdown / JSON / text.
- Billing and subscriptions (metadata only).
- External SSO providers (abstraction exists).
- Daily overnight digest email (architecture ready; template not scheduled yet).
