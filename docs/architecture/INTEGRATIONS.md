# Integrations

## Model

| Table | Content |
|---|---|
| `integrations` | provider key, name, enabled, status, scopes, non-secret config, health, last check and sync |
| `integration_credentials` | Fernet ciphertext, last 4 characters, who set it |

Secrets are write-only through the API, encrypted with `ENCRYPTION_KEYS` (MultiFernet, rotatable), decrypted
only in memory for the call that needs them, never logged and never sent to a model. Every change is audited
with metadata only.

## Available in V1

| Provider | Purpose |
|---|---|
| `ai_provider` | OpenAI-compatible LLM and embeddings per organization (base URL, models, key, connection test) |
| `web_search` | Tavily web search for research agents |
| `social_sandbox` | Demonstrates Level 2 and 3 actions; records posts and never calls a real network |
| Email | Platform provider abstraction: SMTP (Mailpit locally) or Resend |

## Adding an integration

1. Add a provider client in `companyos/providers/`.
2. Register tools in `TOOL_REGISTRY` with a risk level and a Pydantic argument model; read the secret with
   `get_integration_secret`.
3. Grant the tools to agents (template, or Agent → Configuration in the UI).
4. The gateway, approvals, audit log and budgets apply automatically.

Planned: GitHub, Gmail, Google Drive and Calendar, Slack, Teams, Metricool, CRMs, analytics and deployment platforms.
