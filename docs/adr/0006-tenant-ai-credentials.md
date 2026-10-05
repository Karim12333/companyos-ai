# ADR-0006: Per-organization AI provider credentials

**Status:** Accepted

## Context
Each customer must use and pay for their own model provider. A platform-wide key would mix costs and
create a single blast radius.

## Decision
Each organization configures an **AI Provider** integration (OpenAI-compatible: base URL, models,
API key) in *Settings → AI Provider*. The key is stored in `integration_credentials` encrypted with
Fernet using `COMPANYOS_ENCRYPTION_KEY` (MultiFernet for rotation). It is write-only: the API returns
only `last4`. The worker decrypts it in memory per activity; it is never logged or sent to the LLM.

Resolution order for an agent call: organization AI provider integration → (dev only, if
`ALLOW_PLATFORM_AI_FALLBACK=true`) platform key from env → offline mock provider.
In production the platform fallback is disabled so tenants never consume the operator's key.
