# ADR-0003: Tenant isolation with organization_id + PostgreSQL RLS

**Status:** Accepted

## Decision
Shared database, shared schema. Every tenant table has `organization_id`. Application code filters by
it and PostgreSQL Row Level Security enforces it (`FORCE ROW LEVEL SECURITY`, non-superuser app role,
transaction-local `app.org_id`). See `docs/architecture/MULTITENANCY.md`.

## Alternatives
Schema-per-tenant / DB-per-tenant: stronger isolation but heavy migrations and ops for a SaaS with many
small tenants. Can be offered later for enterprise tenants.
