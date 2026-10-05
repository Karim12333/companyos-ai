# ADR-0004: Server-Sent Events for realtime updates

**Status:** Accepted

## Decision
Realtime is one-directional (server → CEO dashboard). We use SSE at
`GET /api/v1/orgs/{org_id}/events/stream`, fed by Redis pub/sub channel `org:{org_id}:events`.
The UI invalidates React Query caches when events arrive and polls slowly as a fallback.

## Why not WebSockets?
No client → server streaming need; SSE works over plain HTTP, reconnects automatically, passes cookies,
and needs no extra protocol handling in proxies.
