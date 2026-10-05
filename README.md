# CompanyOS

> Run a company. Lead AI teams. Approve what matters.

CompanyOS is a multi-tenant SaaS platform where a human acts as the CEO of an AI organization:
departments, managers and specialist agents that plan, execute, review and report on business
objectives — durably, in parallel, and with human approval for anything risky.

Give it one objective before going to sleep. The Chief of Staff plans it, specialists work in parallel,
a reviewer checks the output, risky actions wait for you, and in the morning you get an executive
report by email.

## What's in V1

| Area | What works |
|---|---|
| Organizations | Signup, multiple isolated organizations per user, RBAC (owner/admin/member/viewer) |
| Tenant isolation | `organization_id` everywhere + PostgreSQL Row Level Security + app checks, with tests |
| Organization model | Software / AI Company template: 5 departments, 9 agents, reporting lines, delegation rights |
| Objectives | Natural-language objective → Chief of Staff plan (persisted task DAG) |
| Execution | Temporal workflow: parallel tasks, review loop, approvals, pause/resume/stop, retry, survives restarts |
| Agents | LangGraph runtime; every tool call passes the **tool gateway + policy engine** |
| Approvals | Level 1/2/3 action risk; Level 3 always waits for the CEO; decisions resume the workflow |
| Outputs | Versioned artifacts in S3/MinIO, executive report (in-app + email), activity feed, agent messages |
| CEO experience | Headquarters, CEO Inbox, objective/department/agent/project/artifact pages, live updates (SSE) |
| Knowledge | Company memory, pgvector document search, feedback → promoted preferences |
| AI providers | Each organization adds its **own OpenAI-compatible key** (encrypted); offline mock otherwise |
| Operations | Usage & cost tracking, budgets, analytics, audit log, platform admin, Mailpit/Resend email |

## Architecture

```
Next.js web ──HTTPS/SSE──► FastAPI (modular monolith) ──► Temporal ──► Worker (workflows + agents)
                                │        │      │                          │
                           PostgreSQL  Redis  MinIO                 LLM provider / email
                           + pgvector
```

Read more: [Overview](docs/architecture/OVERVIEW.md) · [Agent system](docs/architecture/AGENT_SYSTEM.md) ·
[Workflows](docs/architecture/WORKFLOWS.md) · [Approvals](docs/architecture/APPROVALS.md) ·
[Security](docs/architecture/SECURITY.md) · [Multi-tenancy](docs/architecture/MULTITENANCY.md) ·
[Memory](docs/architecture/MEMORY.md) · [Integrations](docs/architecture/INTEGRATIONS.md) ·
[Data model](docs/architecture/DATA_MODEL.md) · [ADRs](docs/adr) · [Vision](docs/product/VISION.md) ·
[V1 scope](docs/product/V1_SCOPE.md)

```
apps/api      Python package `companyos`: API, services, agents, tools, workflows, worker
apps/web      Next.js App Router web application
infrastructure/database   Postgres bootstrap (app role, test database)
docs          Product, architecture and ADRs
scripts       Developer scripts
```

## Prerequisites

- Docker Desktop
- Python 3.12+ (3.13 tested)
- Node.js 22+ and pnpm 10+

## Local setup

```bash
# 1. Environment (generates random SECRET_KEY and ENCRYPTION_KEYS)
python scripts/setup_env.py            # optional: ADMIN_EMAIL=you@company.com python scripts/setup_env.py

# 2. Infrastructure: Postgres+pgvector (5442), Redis, Temporal (+UI :8088), MinIO (:9001), Mailpit (:8025)
docker compose up -d postgres redis temporal temporal-ui minio mailpit

# 3. Backend
cd apps/api
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"      # macOS/Linux: .venv/bin/pip
.venv/Scripts/alembic upgrade head         # migrations (runs as the owner role)
.venv/Scripts/python -m companyos.seed     # ByteRoot Labs Demo organization

# 4. Run (three terminals)
.venv/Scripts/uvicorn companyos.main:app --port 8000     # API  → http://localhost:8000/docs
.venv/Scripts/python -m companyos.worker                 # durable worker

cd apps/web && pnpm install && pnpm dev                  # Web  → http://localhost:3100
```

Or run everything in containers: `docker compose --profile app up --build`.

**Demo login:** `ceo@byteroot.demo` / `CompanyOS-demo-2026` (local seed only).
Add `--run-objective` to the seed command to start the demo objective immediately.

| Service | URL |
|---|---|
| Web app | http://localhost:3100 |
| API docs | http://localhost:8000/docs |
| Temporal UI | http://localhost:8088 |
| Mailpit (dev emails) | http://localhost:8025 |
| MinIO console | http://localhost:9001 (`companyos` / `companyos_dev_secret`) |

## Using your own AI key

Each organization uses **its own** provider — keys are never shared between tenants.

1. Sign in, open **Integrations → AI Provider (OpenAI-compatible)**.
2. Enter the base URL (default OpenAI), models and your API key, then **Save provider** and **Test connection**.
3. New work uses your provider; usage and cost appear in **Analytics**.

The key is encrypted at rest (Fernet, `ENCRYPTION_KEYS`), never returned by the API (only the last 4
characters), never logged and never sent to the model. Without a key, agents use an offline mock model
and every artifact is labeled as mock output.

## Tests

```bash
# Backend: unit, API, authorization, tenant isolation, durable workflow tests
cd apps/api
.venv/Scripts/ruff check companyos tests && .venv/Scripts/mypy companyos
TEST_TEMPORAL_ADDRESS=localhost:7233 .venv/Scripts/pytest -q    # omit the variable to auto-start a Temporal dev server

# Frontend
cd apps/web
pnpm lint && pnpm typecheck && pnpm test && pnpm build

# End-to-end (API, worker and web must be running)
PLAYWRIGHT_BROWSERS_PATH=0 npx playwright install chromium
PLAYWRIGHT_BROWSERS_PATH=0 pnpm e2e
```

CI (`.github/workflows/ci.yml`) runs backend lint, type checks and tests, and frontend lint, type checks,
tests and build on every push and pull request.

## Configuration

See [`.env.example`](.env.example). Key settings:

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Session / CSRF signing secret |
| `ENCRYPTION_KEYS` | Comma-separated Fernet keys for tenant secrets (first encrypts; all decrypt → rotation) |
| `DATABASE_URL` / `MIGRATION_DATABASE_URL` | App role (RLS-restricted) / owner role for migrations |
| `EMAIL_PROVIDER` | `smtp` (Mailpit locally) or `resend` with `RESEND_API_KEY` |
| `PLATFORM_ADMIN_EMAILS` | Users who become platform administrators on signup |
| `ALLOW_PLATFORM_AI_FALLBACK` | Dev only: use `PLATFORM_AI_API_KEY` for orgs without their own key |

## Known limitations (V1)

- Artifacts are Markdown/text; PPTX/XLSX/PDF generation is not implemented yet.
- Integrations: AI provider, web search (Tavily), Resend email and a social *sandbox*. GitHub, Gmail, Slack… are planned.
- No drag-and-drop Organization Designer yet (the data model supports it; agents are editable via forms).
- External SSO / MFA not implemented (auth provider abstraction in place).
- The daily overnight summary email is not scheduled yet.
- E2E tests run locally against the running stack; they are not yet part of CI.
