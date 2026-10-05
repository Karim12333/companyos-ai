"use client";

import { KeyRound, Lock } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Badge, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, PageHeader } from "@/components/ui/card";
import { ErrorState, PageSkeleton } from "@/components/ui/feedback";
import { Field, FormError, Input } from "@/components/ui/form";
import { dateTime } from "@/lib/format";
import { useOrgMutation } from "@/lib/hooks";
import { useOrg, useOrgQuery } from "@/lib/session";
import type { Integration } from "@/lib/types";

const PLANNED = ["GitHub", "Gmail", "Google Drive", "Google Calendar", "Slack", "Microsoft Teams", "Metricool", "CRMs"];

export default function IntegrationsPage() {
  const { data, error, isPending } = useOrgQuery<Integration[]>(["integrations"], "/integrations");
  if (isPending) return <PageSkeleton />;
  if (error) return <ErrorState error={error} />;
  const byKey = new Map(data.map((item) => [item.provider_key, item]));

  return (
    <div className="mx-auto max-w-4xl space-y-6">
      <PageHeader
        title="Integrations"
        description="Connections your agents may use. Secrets are encrypted at rest, never shown again after saving, and never sent to the AI model."
      />
      <AIProviderCard integration={byKey.get("ai_provider")} />
      <WebSearchCard integration={byKey.get("web_search")} />
      {byKey.get("social_sandbox") && (
        <Card>
          <CardHeader
            title="Social Publishing (Sandbox)"
            description="Demonstrates Level 3 actions: posts are recorded, never sent to a real network, and only after your approval."
            action={<StatusBadge status="connected" />}
          />
        </Card>
      )}
      <Card className="p-5">
        <h2 className="text-sm font-semibold">Planned integrations</h2>
        <p className="mt-1 text-[13px] text-muted">The provider and tool abstractions are ready for these; they are not available yet.</p>
        <div className="mt-3 flex flex-wrap gap-2">
          {PLANNED.map((name) => (
            <Badge key={name}>{name}</Badge>
          ))}
        </div>
      </Card>
    </div>
  );
}

function SecretStatus({ integration }: { integration?: Integration }) {
  if (!integration?.has_secret) return <span className="text-[13px] text-muted">No key saved</span>;
  return (
    <span className="inline-flex items-center gap-1.5 text-[13px] text-ink-soft">
      <Lock className="size-3.5 text-success" /> Key saved, encrypted · ending in <span className="font-mono">{integration.secret_last4}</span>
    </span>
  );
}

function AIProviderCard({ integration }: { integration?: Integration }) {
  const org = useOrg();
  const [message, setMessage] = useState<string | null>(null);
  const save = useOrgMutation<Record<string, unknown>, Integration>((json) => ({ path: "/integrations/ai-provider", method: "PUT", json }), {
    onSuccess: () => setMessage("Saved. Agents will use this provider for new work."),
  });
  const test = useOrgMutation<void, Integration>(() => ({ path: "/integrations/ai-provider/test" }), {
    onSuccess: (result) => setMessage(result.health_message),
  });
  const remove = useOrgMutation<void>(() => ({ path: "/integrations/ai_provider/secret", method: "DELETE" }));
  const config = integration?.config ?? {};

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const key = String(form.get("api_key") ?? "").trim();
    setMessage(null);
    save.mutate({
      base_url: form.get("base_url"),
      default_model: form.get("default_model"),
      premium_model: form.get("premium_model"),
      embedding_model: form.get("embedding_model"),
      api_key: key || null,
      enabled: true,
    });
    event.currentTarget.reset();
  }

  return (
    <Card>
      <CardHeader
        title="AI Provider (OpenAI-compatible)"
        description="Your organization's own model provider and key. Usage and cost are tracked per agent, task and objective."
        action={<StatusBadge status={integration?.status ?? "not_configured"} />}
      />
      <form onSubmit={submit} className="space-y-4 border-t border-border px-5 py-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Base URL" htmlFor="base_url" hint="OpenAI, Azure OpenAI, OpenRouter, Together, a local server…">
            <Input id="base_url" name="base_url" defaultValue={config.base_url ?? "https://api.openai.com/v1"} disabled={!org.canManage} required />
          </Field>
          <Field label="API key" htmlFor="api_key" hint={<SecretStatus integration={integration} />}>
            <Input id="api_key" name="api_key" type="password" autoComplete="off" placeholder={integration?.has_secret ? "Leave empty to keep the saved key" : "sk-…"} disabled={!org.canManage} />
          </Field>
          <Field label="Default model" htmlFor="default_model">
            <Input id="default_model" name="default_model" defaultValue={config.default_model ?? "gpt-4o-mini"} disabled={!org.canManage} required />
          </Field>
          <Field label="Premium model" htmlFor="premium_model" hint="Used by the Chief of Staff and Architect.">
            <Input id="premium_model" name="premium_model" defaultValue={config.premium_model ?? "gpt-4o"} disabled={!org.canManage} required />
          </Field>
          <Field label="Embedding model" htmlFor="embedding_model" hint="Use local-hash-1536 if your provider has no embeddings endpoint.">
            <Input id="embedding_model" name="embedding_model" defaultValue={config.embedding_model ?? "text-embedding-3-small"} disabled={!org.canManage} required />
          </Field>
        </div>
        {integration?.last_checked_at && (
          <p className="text-xs text-muted">
            Last checked {dateTime(integration.last_checked_at)}: {integration.health_message}
          </p>
        )}
        {message && <p className="text-[13px] text-success">{message}</p>}
        <FormError message={save.error?.message ?? test.error?.message ?? remove.error?.message} />
        {org.canManage ? (
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="primary" loading={save.isPending}>
              <KeyRound className="size-4" /> Save provider
            </Button>
            <Button type="button" onClick={() => test.mutate()} loading={test.isPending} disabled={!integration?.has_secret}>
              Test connection
            </Button>
            {integration?.has_secret && (
              <Button type="button" variant="danger" onClick={() => window.confirm("Remove the saved API key? Agents will fall back to the offline mock model.") && remove.mutate()}>
                Remove key
              </Button>
            )}
          </div>
        ) : (
          <p className="text-[13px] text-muted">Only owners and admins can change integrations.</p>
        )}
      </form>
    </Card>
  );
}

function WebSearchCard({ integration }: { integration?: Integration }) {
  const org = useOrg();
  const save = useOrgMutation<string>((api_key) => ({ path: "/integrations/web-search", method: "PUT", json: { api_key } }));
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const key = String(new FormData(event.currentTarget).get("tavily_key") ?? "").trim();
    if (key) save.mutate(key);
    event.currentTarget.reset();
  }
  return (
    <Card>
      <CardHeader
        title="Web Search (Tavily)"
        description="Lets research agents search the public web. Results are treated as untrusted data."
        action={<StatusBadge status={integration?.status ?? "not_configured"} />}
      />
      {org.canManage && (
        <form onSubmit={submit} className="flex flex-col gap-3 border-t border-border px-5 py-4 sm:flex-row sm:items-end">
          <div className="flex-1">
            <Field label="Tavily API key" htmlFor="tavily_key" hint={<SecretStatus integration={integration} />}>
              <Input id="tavily_key" name="tavily_key" type="password" autoComplete="off" placeholder="tvly-…" />
            </Field>
          </div>
          <Button type="submit" loading={save.isPending}>
            Save key
          </Button>
        </form>
      )}
    </Card>
  );
}
