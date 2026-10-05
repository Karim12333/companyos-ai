# Security

CompanyOS is a multi-tenant system that lets AI agents take actions. Security is enforced in code and
in the database — never by prompts alone.

## Authentication

- Local email/password auth for V1 behind `AuthProvider` (swap for an external IdP later).
- Passwords hashed with **argon2id** (`argon2-cffi`). Minimum length enforced.
- Sessions are **server-side**: a random 256-bit token is set in an `HttpOnly`, `SameSite=Lax`
  (`Secure` in production) cookie; only its SHA-256 hash is stored in `user_sessions`.
  Logout revokes the session row.
- Login is rate limited per IP and per email (Redis fixed window).

## CSRF

Cookie auth requires CSRF protection. Every mutating request (`POST/PUT/PATCH/DELETE`) must send
`X-CSRF-Token`, which equals `HMAC(secret, session_token)`. The token is returned by `/auth/me`
and held in memory by the web app. A cross-site attacker cannot read it. `SameSite=Lax` adds defense
in depth.

## CORS

Only origins listed in `CORS_ORIGINS` are allowed, with credentials. No wildcard.

## Authorization

1. **Organization membership** — every `/orgs/{org_id}/…` route requires membership.
2. **RBAC** — role → permission map (`owner`, `admin`, `member`, `viewer`).
3. **Object-level** — objects are always loaded with `organization_id = :org_id`; RLS guarantees it
   even if a query forgets the filter (IDOR protection).
4. **Platform admin** — separate `is_platform_admin` flag; organization admins cannot reach platform
   endpoints.

## Tenant isolation

See `MULTITENANCY.md`. PostgreSQL RLS (`FORCE ROW LEVEL SECURITY`) on every tenant table, with the
application connecting as a non-superuser role. Covered by tenant isolation tests.

## Agent / tool security (the Tool Gateway)

```
Agent (LLM) ──tool request──► Tool Gateway ──► Policy Engine ──► Tool
                                   │                 │
                                   └── audit log ◄───┘
```

Before any tool executes, the gateway checks:

- agent identity and that the agent belongs to the organization,
- the tool is registered and enabled for the agent (`agent_tools`),
- action risk level (1 autonomous / 2 controlled / 3 human approval),
- agent permissions (`agent_permissions`), organization approval policies and objective policy,
- usage/budget limits and iteration limits,
- argument schema validation (Pydantic) — the LLM cannot pass arbitrary arguments.

Level 3 actions **always** create an approval and stop. Denied or approval-required requests are written
to `audit_logs`. The LLM never receives credentials.

## Prompt injection

External content (web results, uploaded documents) is wrapped in delimited `<untrusted_content>` blocks
with an explicit instruction that it is data, not instructions. Tool permissions are enforced by the
gateway regardless of what the model says, so injected instructions cannot escalate privileges.

## Secrets

- Integration secrets (including each organization's AI API key) are encrypted with **Fernet**
  (AES-128-CBC + HMAC-SHA256) using `COMPANYOS_ENCRYPTION_KEY`; `MultiFernet` supports rotation.
- Secrets are write-only from the UI; only the last 4 characters are ever returned.
- A log processor redacts keys such as `password`, `api_key`, `token`, `secret`, `authorization`.
- `.env` is git-ignored; `.env.example` contains no real values.

## Files and artifacts

- Uploads validated for size and MIME allow-list.
- Artifacts are stored under `org/{organization_id}/…` keys and only served through an authorized
  API endpoint (no public bucket). Content is served with `Content-Disposition` and
  `X-Content-Type-Options: nosniff`.

## Audit

`audit_logs` records authentication events, membership changes, settings / credential changes,
approval decisions and every gateway decision for tool execution.

## Known V1 limitations

- No MFA / SSO yet (provider abstraction prepared).
- Rate limiting covers auth and objective creation; general API rate limits are configurable later.
