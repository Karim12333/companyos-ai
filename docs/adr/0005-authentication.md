# ADR-0005: Local session authentication behind a provider abstraction

**Status:** Accepted

## Decision
V1 ships local email/password auth (argon2id) with server-side sessions in an HttpOnly cookie and an
HMAC-derived CSRF header token. Auth is accessed via `AuthProvider` so an external IdP
(Auth0, Clerk, WorkOS, Cognito) can replace it without touching the domain model:
the domain only knows `users.id`, `email`, and memberships.

## Why server-side sessions over JWT?
Immediate revocation (logout, compromised account) and no token-size/rotation complexity.
