"use client";

import { Search, ShieldAlert } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, PageHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/ui/feedback";
import { Field, FormError, Input, Select, Textarea } from "@/components/ui/form";
import { Tabs } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { humanize, timeAgo } from "@/lib/format";
import { useAgents, useOrgMutation } from "@/lib/hooks";
import { useOrg, useOrgQuery } from "@/lib/session";

type Tab = "memory" | "documents" | "preferences" | "search";

interface Memory { id: string; category: string; title: string; content: string; is_active: boolean }
interface Doc { id: string; title: string; source: string; chunk_count: number; is_untrusted: boolean; created_at: string }
interface Preference { id: string; scope: string; agent_id: string | null; content: string; is_active: boolean; source_feedback_id: string | null }
interface Feedback { id: string; comment: string; status: string; agent_id: string | null; created_at: string }

export default function KnowledgePage() {
  const [tab, setTab] = useState<Tab>("memory");
  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader
        title="Company knowledge"
        description="Structured facts every agent follows, long-form documents retrieved by meaning, and CEO preferences learned from feedback."
      />
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { value: "memory", label: "Company memory" },
          { value: "documents", label: "Documents" },
          { value: "preferences", label: "Preferences & feedback" },
          { value: "search", label: "Search" },
        ]}
      />
      <div className="mt-5">
        {tab === "memory" && <MemoryTab />}
        {tab === "documents" && <DocumentsTab />}
        {tab === "preferences" && <PreferencesTab />}
        {tab === "search" && <SearchTab />}
      </div>
    </div>
  );
}

function MemoryTab() {
  const org = useOrg();
  const { data, error, isPending } = useOrgQuery<Memory[]>(["knowledge", "memory"], "/knowledge/memory");
  const create = useOrgMutation<Record<string, unknown>>((json) => ({ path: "/knowledge/memory", json }));
  const remove = useOrgMutation<string>((id) => ({ path: `/knowledge/memory/${id}`, method: "DELETE" }));
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    create.mutate({ category: form.get("category"), title: form.get("title"), content: form.get("content") });
    event.currentTarget.reset();
  }
  if (isPending) return <PageSkeleton />;
  if (error) return <ErrorState error={error} />;
  const active = data.filter((item) => item.is_active);
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
      <Card>
        {active.length === 0 ? (
          <EmptyState title="No company facts yet" description="Add your identity, mission, brand voice, policies and products." />
        ) : (
          <ul className="divide-y divide-border">
            {active.map((item) => (
              <li key={item.id} className="flex items-start gap-3 px-5 py-3.5">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <Badge>{humanize(item.category)}</Badge>
                    <span className="text-sm font-medium">{item.title}</span>
                  </div>
                  <p className="mt-1 text-[13.5px] text-ink-soft">{item.content}</p>
                </div>
                {org.canEdit && (
                  <Button size="sm" variant="ghost" onClick={() => remove.mutate(item.id)}>
                    Remove
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
      {org.canEdit && (
        <Card className="h-fit p-5">
          <form onSubmit={submit} className="space-y-3">
            <h2 className="text-sm font-semibold">Add a company fact</h2>
            <Field label="Category" htmlFor="category">
              <Select id="category" name="category" defaultValue="brand">
                {["identity", "mission", "brand", "policy", "product", "business_rule"].map((value) => (
                  <option key={value} value={value}>
                    {humanize(value)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Title" htmlFor="memory-title">
              <Input id="memory-title" name="title" required />
            </Field>
            <Field label="Content" htmlFor="memory-content">
              <Textarea id="memory-content" name="content" rows={4} required />
            </Field>
            <FormError message={create.error?.message} />
            <Button type="submit" variant="primary" loading={create.isPending}>
              Add fact
            </Button>
          </form>
        </Card>
      )}
    </div>
  );
}

function DocumentsTab() {
  const org = useOrg();
  const { data, error, isPending } = useOrgQuery<Doc[]>(["knowledge", "documents"], "/knowledge/documents");
  const create = useOrgMutation<Record<string, unknown>>((json) => ({ path: "/knowledge/documents", json }));
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    create.mutate({ title: form.get("title"), content: form.get("content"), trusted: form.get("trusted") === "on" });
    event.currentTarget.reset();
  }
  if (isPending) return <PageSkeleton />;
  if (error) return <ErrorState error={error} />;
  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
      <Card>
        {data.length === 0 ? (
          <EmptyState title="No documents" description="Documents are chunked, embedded with pgvector and retrieved by agents when relevant." />
        ) : (
          <ul className="divide-y divide-border">
            {data.map((document) => (
              <li key={document.id} className="flex items-center justify-between gap-3 px-5 py-3">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{document.title}</p>
                  <p className="text-xs text-muted">
                    {document.chunk_count} chunks · {document.source} · {timeAgo(document.created_at)}
                  </p>
                </div>
                {document.is_untrusted && (
                  <Badge tone="warning">
                    <ShieldAlert className="size-3" /> Untrusted
                  </Badge>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
      {org.canEdit && (
        <Card className="h-fit p-5">
          <form onSubmit={submit} className="space-y-3">
            <h2 className="text-sm font-semibold">Add a document</h2>
            <Field label="Title" htmlFor="doc-title">
              <Input id="doc-title" name="title" required />
            </Field>
            <Field label="Content (Markdown or text)" htmlFor="doc-content">
              <Textarea id="doc-content" name="content" rows={8} required minLength={10} />
            </Field>
            <label className="flex items-start gap-2 text-[13px] text-ink-soft">
              <input type="checkbox" name="trusted" className="mt-0.5 size-4 accent-[var(--accent)]" />
              Written by us (trusted). Leave unchecked for external content — agents will treat it as data, not instructions.
            </label>
            <FormError message={create.error?.message} />
            <Button type="submit" variant="primary" loading={create.isPending}>
              Add and index
            </Button>
          </form>
        </Card>
      )}
    </div>
  );
}

function PreferencesTab() {
  const org = useOrg();
  const agents = useAgents();
  const preferences = useOrgQuery<Preference[]>(["knowledge", "preferences"], "/knowledge/preferences");
  const feedback = useOrgQuery<Feedback[]>(["knowledge", "feedback"], "/knowledge/feedback");
  const promote = useOrgMutation<{ id: string; scope: string }>(({ id, scope }) => ({ path: `/knowledge/feedback/${id}/promote`, json: { scope } }));
  const dismiss = useOrgMutation<string>((id) => ({ path: `/knowledge/feedback/${id}/dismiss` }));
  const toggle = useOrgMutation<string>((id) => ({ path: `/knowledge/preferences/${id}/toggle` }));
  const create = useOrgMutation<string>((content) => ({ path: "/knowledge/preferences", json: { content } }));
  const [draft, setDraft] = useState("");

  if (preferences.isPending || feedback.isPending) return <PageSkeleton />;
  if (preferences.error) return <ErrorState error={preferences.error} />;
  const open = (feedback.data ?? []).filter((item) => item.status === "open");

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card>
        <CardHeader title="Active preferences" description="Injected into every relevant agent's instructions." />
        <ul className="divide-y divide-border border-t border-border">
          {preferences.data.length === 0 && <li className="px-5 py-4 text-[13px] text-muted">No preferences yet.</li>}
          {preferences.data.map((preference) => (
            <li key={preference.id} className="flex items-start gap-3 px-5 py-3">
              <div className="min-w-0 flex-1">
                <p className={preference.is_active ? "text-[13.5px]" : "text-[13.5px] text-faint line-through"}>{preference.content}</p>
                <p className="mt-0.5 text-xs text-muted">
                  {preference.scope === "agent" ? `Agent: ${agents.byId.get(preference.agent_id ?? "")?.name ?? "—"}` : "Organization-wide"}
                  {preference.source_feedback_id && " · from feedback"}
                </p>
              </div>
              {org.canEdit && (
                <Button size="sm" variant="ghost" onClick={() => toggle.mutate(preference.id)}>
                  {preference.is_active ? "Disable" : "Enable"}
                </Button>
              )}
            </li>
          ))}
        </ul>
        {org.canEdit && (
          <form
            className="flex gap-2 border-t border-border px-5 py-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (draft.trim()) create.mutate(draft.trim(), { onSuccess: () => setDraft("") });
            }}
          >
            <Input aria-label="New preference" value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="e.g. Write technically, concisely and directly." />
            <Button type="submit" loading={create.isPending}>
              Add
            </Button>
          </form>
        )}
      </Card>
      <Card>
        <CardHeader title="Feedback to review" description="Not every comment should become permanent. Promote what should last." />
        <ul className="divide-y divide-border border-t border-border">
          {open.length === 0 && <li className="px-5 py-4 text-[13px] text-muted">No open feedback. Add feedback from any artifact.</li>}
          {open.map((item) => (
            <li key={item.id} className="px-5 py-3">
              <p className="text-[13.5px]">{item.comment}</p>
              <p className="mt-0.5 text-xs text-muted">
                {item.agent_id ? agents.byId.get(item.agent_id)?.name : "General"} · {timeAgo(item.created_at)}
              </p>
              {org.canEdit && (
                <div className="mt-2 flex flex-wrap gap-2">
                  <Button size="sm" onClick={() => promote.mutate({ id: item.id, scope: "organization" })}>
                    Make company preference
                  </Button>
                  {item.agent_id && (
                    <Button size="sm" onClick={() => promote.mutate({ id: item.id, scope: "agent" })}>
                      Only for this agent
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" onClick={() => dismiss.mutate(item.id)}>
                    Dismiss
                  </Button>
                </div>
              )}
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

function SearchTab() {
  const org = useOrg();
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<{ facts: Memory[]; chunks: { document_title: string; content: string; score: number }[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      setResult(await api(org.path(`/knowledge/search?q=${encodeURIComponent(query)}`)));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Search failed");
    }
  }
  return (
    <div className="space-y-4">
      <form onSubmit={submit} className="flex gap-2">
        <Input aria-label="Search knowledge" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="What do agents know about…" minLength={2} required />
        <Button type="submit">
          <Search className="size-4" /> Search
        </Button>
      </form>
      <FormError message={error} />
      {result && (
        <Card>
          <CardHeader title="Retrieved document passages" description="Exactly what an agent would receive from the knowledge tool." />
          <ul className="divide-y divide-border border-t border-border">
            {result.chunks.length === 0 && <li className="px-5 py-4 text-[13px] text-muted">No matching documents.</li>}
            {result.chunks.map((chunk, index) => (
              <li key={index} className="px-5 py-3">
                <p className="text-xs text-muted">
                  {chunk.document_title} · similarity {chunk.score.toFixed(2)}
                </p>
                <p className="mt-1 line-clamp-4 text-[13px] whitespace-pre-line text-ink-soft">{chunk.content}</p>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
