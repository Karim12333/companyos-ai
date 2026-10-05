# Multi-tenancy

Company A must never see Company B's data. Isolation is enforced at three layers.

## 1. Data model

Every tenant-owned table has a non-null `organization_id` foreign key. Composite indexes start with
`organization_id`.

## 2. Application layer

- API routes are shaped `/api/v1/orgs/{org_id}/…`. A dependency verifies the caller is a member of
  `org_id` and resolves their role before any handler runs.
- Services always filter by `organization_id`.
- Workers carry `organization_id` in every workflow and activity input and open their DB session with
  that tenant context.

## 3. Database (Row Level Security)

All tenant tables have:

```sql
ALTER TABLE <t> ENABLE ROW LEVEL SECURITY;
ALTER TABLE <t> FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON <t>
  USING (organization_id = app_current_org() OR app_rls_bypass())
  WITH CHECK (organization_id = app_current_org() OR app_rls_bypass());
```

`app_current_org()` reads `current_setting('app.org_id', true)`. Each transaction sets it with
`set_config('app.org_id', …, true)` (transaction-local), so pooled connections cannot leak context.

The application connects as `companyos_app`, a **non-superuser** role (superusers bypass RLS).
Migrations run as the owner role.

### Special cases

| Table | Policy |
|---|---|
| `organizations` | visible when `id = app.org_id`, or the current user is a member |
| `organization_members` | visible when in current org, or `user_id = app.user_id` (list my orgs) |
| `audit_logs` | tenant rows by org; platform rows (`organization_id IS NULL`) only with bypass |

### Bypass

`app.rls_bypass = on` is set only by trusted system code paths: signup (creating a new tenant),
platform-admin endpoints, and cross-tenant maintenance. It is never derived from user input.

## Tests

`apps/api/tests/test_tenant_isolation.py` proves:

- API: a member of org A gets `403/404` for org B resources (objectives, agents, artifacts, approvals,
  inbox, knowledge, integrations).
- Database: with `app.org_id = A`, raw SQL `SELECT` over tenant tables returns no rows of org B, and
  `INSERT` of org B rows is rejected by the policy.
