# API

The API is self-documented with OpenAPI. Run the API and open http://localhost:8000/docs.

- All tenant routes are scoped as `/api/v1/orgs/{org_id}/...` and require membership.
- Authentication uses an HttpOnly session cookie; mutating requests must send `X-CSRF-Token` (returned by `GET /api/v1/auth/me`).
- Live updates: `GET /api/v1/orgs/{org_id}/events/stream` (Server-Sent Events).
- Health: `GET /health/live`, `GET /health/ready`.
