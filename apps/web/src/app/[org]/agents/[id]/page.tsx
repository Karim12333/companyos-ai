"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { ActivityFeed } from "@/components/activity-feed";
import { Badge, RiskBadge, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, Stat } from "@/components/ui/card";
import { Avatar, EmptyState, ErrorState, PageSkeleton } from "@/components/ui/feedback";
import { Field, FormError, Input, Textarea } from "@/components/ui/form";
import { Tabs } from "@/components/ui/tabs";
import { between, clock, compact, duration, humanize, usd } from "@/lib/format";
import { useAgents, useOrgMutation } from "@/lib/hooks";
import { useOrg, useOrgQuery } from "@/lib/session";
import type { ActivityEvent, Agent, AgentDetail, AgentMessage, Artifact, Department, Objective, Task } from "@/lib/types";

interface AgentPayload {
  agent: AgentDetail;
  department: Department | null;
  manager: Agent | null;
  delegates: Agent[];
  current_task: Task | null;
  current_objective: Objective | null;
  completed_tasks: Task[];
  failed_tasks: Task[];
  stats: { completed: number; failed: number; revisions: number };
  messages: AgentMessage[];
  artifacts: Artifact[];
  activity: ActivityEvent[];
  tools: { key: string; enabled: boolean; risk_level: string | null; description: string; permission: string | null }[];
  usage: { input_tokens: number; output_tokens: number; cost_usd: number; calls: number };
}

type Tab = "overview" | "work" | "communication" | "artifacts" | "configuration";

export default function AgentPage() {
  const org = useOrg();
  const { id } = useParams<{ id: string }>();
  const [tab, setTab] = useState<Tab>("overview");
  const agents = useAgents();
  const { data, error, isPending } = useOrgQuery<AgentPayload>(["agent", id], `/agents/${id}`);
  if (isPending) return <PageSkeleton />;
  if (error) return <ErrorState error={error} />;
  const { agent } = data;

  return (
    <div className="space-y-6">
      <div>
        <Link href={org.href("/agents")} className="text-[13px] text-muted hover:text-ink">
          Agents
        </Link>
        <div className="mt-2 flex items-center gap-4">
          <Avatar name={agent.name} className="size-12 rounded-xl text-sm" />
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-[22px] font-semibold tracking-tight">{agent.name}</h1>
              <StatusBadge status={agent.is_active ? agent.status : "disabled"} />
              {agent.is_coordinator && <Badge tone="accent">Coordinator</Badge>}
            </div>
            <p className="text-sm text-muted">
              {agent.title}
              {data.department && (
                <>
                  {" · "}
                  <Link href={org.href(`/departments/${data.department.id}`)} className="hover:underline">
                    {data.department.name}
                  </Link>
                </>
              )}
              {" · reports to "}
              {data.manager ? (
                <Link href={org.href(`/agents/${data.manager.id}`)} className="hover:underline">
                  {data.manager.name}
                </Link>
              ) : (
                "CEO"
              )}
            </p>
          </div>
        </div>
      </div>

      <Card className="p-5">
        <h2 className="text-xs font-semibold tracking-wide text-muted uppercase">Current assignment</h2>
        {data.current_task ? (
          <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <Link href={org.href(`/objectives/${data.current_task.objective_id}?task=${data.current_task.id}`)} className="text-[15px] font-medium hover:underline">
                {data.current_task.title}
              </Link>
              <p className="text-[13px] text-muted">
                {data.current_objective?.title} · started {clock(data.current_task.started_at)} ·{" "}
                {duration(between(data.current_task.started_at, null))} elapsed
              </p>
            </div>
            <StatusBadge status={data.current_task.status} />
          </div>
        ) : (
          <p className="mt-2 text-sm text-muted">Idle — waiting for the next assignment.</p>
        )}
      </Card>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Tasks completed" value={data.stats.completed} />
        <Stat label="Failed" value={data.stats.failed} />
        <Stat label="Revisions requested" value={data.stats.revisions} />
        <Stat label="AI cost" value={usd(data.usage.cost_usd)} hint={`${compact(data.usage.input_tokens + data.usage.output_tokens)} tokens · ${data.usage.calls} calls`} />
      </div>

      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { value: "overview", label: "Overview" },
          { value: "work", label: "Work", count: data.completed_tasks.length + data.failed_tasks.length },
          { value: "communication", label: "Communication", count: data.messages.length },
          { value: "artifacts", label: "Artifacts", count: data.artifacts.length },
          { value: "configuration", label: "Configuration" },
        ]}
      />

      {tab === "overview" && (
        <div className="grid gap-6 lg:grid-cols-3">
          <Card className="space-y-5 p-5 lg:col-span-2">
            <p className="text-[14px] text-ink-soft">{agent.description}</p>
            <div className="grid gap-5 sm:grid-cols-2">
              <div>
                <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">Goals</h3>
                <ul className="mt-2 list-disc space-y-1 pl-4 text-[13.5px] text-ink-soft">
                  {agent.goals.map((goal) => (
                    <li key={goal}>{goal}</li>
                  ))}
                </ul>
              </div>
              <div>
                <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">Responsibilities</h3>
                <ul className="mt-2 list-disc space-y-1 pl-4 text-[13.5px] text-ink-soft">
                  {agent.responsibilities.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>
            </div>
            <div>
              <h3 className="text-xs font-semibold tracking-wide text-muted uppercase">Can delegate to</h3>
              <div className="mt-2 flex flex-wrap gap-2">
                {data.delegates.length === 0 && <span className="text-[13px] text-muted">No delegation rights</span>}
                {data.delegates.map((delegate) => (
                  <Link key={delegate.id} href={org.href(`/agents/${delegate.id}`)}>
                    <Badge>{delegate.name}</Badge>
                  </Link>
                ))}
              </div>
            </div>
          </Card>
          <Card>
            <CardHeader title="Recent activity" />
            <div className="border-t border-border">
              <ActivityFeed events={data.activity.slice(0, 12)} compact />
            </div>
          </Card>
        </div>
      )}

      {tab === "work" && (
        <Card>
          {data.completed_tasks.length + data.failed_tasks.length === 0 ? (
            <EmptyState title="No finished work yet" />
          ) : (
            <ul className="divide-y divide-border">
              {[...data.failed_tasks, ...data.completed_tasks].map((task) => (
                <li key={task.id}>
                  <Link href={org.href(`/objectives/${task.objective_id}?task=${task.id}`)} className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-surface-hover">
                    <div className="min-w-0">
                      <p className="truncate text-sm">{task.title}</p>
                      <p className="text-xs text-muted">
                        {duration(between(task.started_at, task.completed_at))}
                        {task.revision_count > 0 && ` · ${task.revision_count} revision(s)`}
                        {task.error_message && ` · ${task.error_message}`}
                      </p>
                    </div>
                    <StatusBadge status={task.status} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {tab === "communication" && (
        <Card>
          {data.messages.length === 0 ? (
            <EmptyState title="No messages yet" />
          ) : (
            <ul className="divide-y divide-border">
              {data.messages.map((message) => {
                const outgoing = message.sender_agent_id === agent.id;
                const other = agents.byId.get((outgoing ? message.recipient_agent_id : message.sender_agent_id) ?? "");
                return (
                  <li key={message.id} className="px-5 py-3">
                    <p className="text-xs text-muted">
                      {outgoing ? "To" : "From"} {other?.name ?? "—"} · {humanize(message.kind)} · {clock(message.created_at)}
                    </p>
                    <p className="mt-0.5 text-sm font-medium">{message.subject}</p>
                    <p className="line-clamp-3 text-[13px] whitespace-pre-line text-ink-soft">{message.body}</p>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      )}

      {tab === "artifacts" && (
        <Card>
          {data.artifacts.length === 0 ? (
            <EmptyState title="No artifacts yet" />
          ) : (
            <ul className="divide-y divide-border">
              {data.artifacts.map((artifact) => (
                <li key={artifact.id}>
                  <Link href={org.href(`/artifacts/${artifact.id}`)} className="flex items-center justify-between px-5 py-3 hover:bg-surface-hover">
                    <span className="truncate text-sm">{artifact.title}</span>
                    <StatusBadge status={artifact.review_status} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {tab === "configuration" && <AgentConfiguration payload={data} />}
    </div>
  );
}

function AgentConfiguration({ payload }: { payload: AgentPayload }) {
  const org = useOrg();
  const { agent } = payload;
  const { data: catalog } = useOrgQuery<{ key: string; description: string; risk_level: string }[]>(["tools"], "/tools");
  const [tools, setTools] = useState(() => new Set(payload.tools.filter((tool) => tool.enabled).map((tool) => tool.key)));
  const [saved, setSaved] = useState(false);
  const update = useOrgMutation<Record<string, unknown>>((json) => ({ path: `/agents/${agent.id}`, method: "PATCH", json }), {
    onSuccess: () => setSaved(true),
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSaved(false);
    update.mutate({
      system_instructions: form.get("system_instructions"),
      model: form.get("model") || null,
      use_premium_model: form.get("use_premium_model") === "on",
      max_iterations: Number(form.get("max_iterations")),
      is_active: form.get("is_active") === "on",
      tool_keys: [...tools],
    });
  }

  const readOnly = !org.canManage;
  return (
    <form onSubmit={submit} className="grid gap-6 lg:grid-cols-[1fr_380px]">
      <Card className="space-y-5 p-5">
        <Field label="System instructions" htmlFor="system_instructions" hint="Platform rules (tool gateway, approvals, untrusted content) are always appended and cannot be removed.">
          <Textarea id="system_instructions" name="system_instructions" rows={8} defaultValue={agent.system_instructions} disabled={readOnly} />
        </Field>
        <div className="grid gap-5 sm:grid-cols-2">
          <Field label="Model override" htmlFor="model" hint="Empty uses the organization default.">
            <Input id="model" name="model" defaultValue={agent.model ?? ""} placeholder="e.g. gpt-4o" disabled={readOnly} />
          </Field>
          <Field label="Max iterations per task" htmlFor="max_iterations" hint="Hard stop for the reasoning loop.">
            <Input id="max_iterations" name="max_iterations" type="number" min={1} max={20} defaultValue={agent.max_iterations} disabled={readOnly} />
          </Field>
        </div>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" name="use_premium_model" defaultChecked={agent.use_premium_model} disabled={readOnly} className="size-4 accent-[var(--accent)]" />
          Use the premium model
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" name="is_active" defaultChecked={agent.is_active} disabled={readOnly} className="size-4 accent-[var(--accent)]" />
          Agent is active
        </label>
        <FormError message={update.error?.message} />
        {!readOnly && (
          <div className="flex items-center gap-3">
            <Button type="submit" variant="primary" loading={update.isPending}>
              Save configuration
            </Button>
            {saved && <span className="text-[13px] text-success">Saved</span>}
          </div>
        )}
      </Card>
      <Card>
        <CardHeader title="Tools & permissions" description="Enforced by the tool gateway, not by prompts." />
        <ul className="divide-y divide-border border-t border-border">
          {(catalog ?? []).map((tool) => (
            <li key={tool.key} className="flex items-start gap-3 px-5 py-3">
              <input
                type="checkbox"
                aria-label={tool.key}
                checked={tools.has(tool.key)}
                disabled={readOnly}
                onChange={(event) => {
                  const next = new Set(tools);
                  if (event.target.checked) next.add(tool.key);
                  else next.delete(tool.key);
                  setTools(next);
                }}
                className="mt-1 size-4 accent-[var(--accent)]"
              />
              <div className="min-w-0">
                <p className="font-mono text-[12.5px]">{tool.key}</p>
                <p className="text-xs text-muted">{tool.description}</p>
                <div className="mt-1">
                  <RiskBadge level={tool.risk_level} />
                </div>
              </div>
            </li>
          ))}
        </ul>
      </Card>
    </form>
  );
}
