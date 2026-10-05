"use client";

import { ArrowRight, Pause, Play, RotateCcw, Square } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { ActivityFeed } from "@/components/activity-feed";
import { ApprovalActions } from "@/components/approval-actions";
import { ExecutiveReport } from "@/components/executive-report";
import { TaskGraph } from "@/components/task-graph";
import { Badge, RiskBadge, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, PageSkeleton, Progress } from "@/components/ui/feedback";
import { FormError } from "@/components/ui/form";
import { Tabs } from "@/components/ui/tabs";
import { between, clock, dateTime, duration, humanize, timeAgo, usd } from "@/lib/format";
import { useAgents, useOrgMutation } from "@/lib/hooks";
import { useOrg, useOrgQuery } from "@/lib/session";
import type { ActivityEvent, Agent, AgentMessage, Approval, Artifact, Objective, Task } from "@/lib/types";

interface ObjectiveDetailData {
  objective: Objective;
  tasks: Task[];
  messages: AgentMessage[];
  approvals: Approval[];
  artifacts: Artifact[];
  activity: ActivityEvent[];
  workflow_runs: { workflow_id: string; status: string; started_at: string | null; finished_at: string | null }[];
}

type Tab = "plan" | "report" | "communication" | "artifacts" | "approvals" | "activity";
const LIVE_STATES = new Set(["PLANNING", "RUNNING", "WAITING_FOR_APPROVAL", "REVIEWING", "WAITING", "PAUSED"]);

export function ObjectiveDetail() {
  const org = useOrg();
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const search = useSearchParams();
  const tab = (search.get("tab") as Tab) ?? "plan";
  const [selectedId, setSelectedId] = useState<string | null>(search.get("task"));
  const agents = useAgents();
  const { data, error, isPending } = useOrgQuery<ObjectiveDetailData>(["objective", params.id], `/objectives/${params.id}`, {
    refetchInterval: 10_000,
  });
  const control = useOrgMutation<string>((action) => ({ path: `/objectives/${params.id}/${action}` }));

  if (isPending) return <PageSkeleton />;
  if (error) return <ErrorState error={error} />;

  const { objective, tasks } = data;
  const live = LIVE_STATES.has(objective.status);
  const selected = tasks.find((task) => task.id === selectedId) ?? null;
  const pending = data.approvals.filter((approval) => approval.status === "PENDING");
  const setTab = (value: Tab) => router.replace(`?tab=${value}`, { scroll: false });

  return (
    <div className="space-y-6">
      <div>
        <Link href={org.href("/objectives")} className="text-[13px] text-muted hover:text-ink">
          Objectives
        </Link>
        <div className="mt-1 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-[22px] font-semibold tracking-tight">{objective.title}</h1>
              <StatusBadge status={objective.status} />
              {objective.approval_policy.external_actions === "deny" && <Badge>External actions blocked</Badge>}
            </div>
            <p className="mt-1 text-sm text-muted">
              {objective.current_stage} · started {timeAgo(objective.started_at ?? objective.created_at)} ·{" "}
              {duration(between(objective.started_at, objective.completed_at))} · {usd(objective.cost_usd)} AI cost
            </p>
          </div>
          {org.canEdit && live && (
            <div className="flex gap-2">
              {objective.is_paused ? (
                <Button size="sm" onClick={() => control.mutate("resume")} loading={control.isPending}>
                  <Play className="size-3.5" /> Resume
                </Button>
              ) : (
                <Button size="sm" onClick={() => control.mutate("pause")} loading={control.isPending}>
                  <Pause className="size-3.5" /> Pause
                </Button>
              )}
              <Button
                size="sm"
                variant="danger"
                onClick={() => {
                  if (window.confirm("Stop all work on this objective?")) control.mutate("cancel");
                }}
              >
                <Square className="size-3.5" /> Stop
              </Button>
            </div>
          )}
          {objective.status === "DRAFT" && org.canEdit && (
            <Button size="sm" variant="primary" onClick={() => control.mutate("start")} loading={control.isPending}>
              <Play className="size-3.5" /> Start
            </Button>
          )}
        </div>
        <div className="mt-4 max-w-xl">
          <Progress value={objective.progress} tone={objective.status === "COMPLETED" ? "success" : "accent"} />
        </div>
        <FormError message={control.error?.message} />
      </div>

      {pending.length > 0 && (
        <Card className="border-warning/30">
          <CardHeader title="Waiting for your approval" description="These actions are paused until you decide." />
          <ul className="divide-y divide-border border-t border-border">
            {pending.map((approval) => (
              <li key={approval.id} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <Link href={org.href(`/approvals/${approval.id}`)} className="text-sm font-medium hover:underline">
                      {approval.title}
                    </Link>
                    <RiskBadge level={approval.risk_level} />
                  </div>
                  <p className="mt-1 text-[13px] text-muted">{approval.summary}</p>
                </div>
                <ApprovalActions approval={approval} />
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { value: "plan", label: "Plan", count: tasks.length },
          { value: "report", label: "Executive report" },
          { value: "communication", label: "Communication", count: data.messages.length },
          { value: "artifacts", label: "Artifacts", count: data.artifacts.length },
          { value: "approvals", label: "Approvals", count: data.approvals.length },
          { value: "activity", label: "Activity" },
        ]}
      />

      {tab === "plan" && (
        <div className="space-y-6">
          <Card className="p-5">
            <h2 className="text-sm font-semibold">CEO instruction</h2>
            <p className="mt-1 text-[13.5px] whitespace-pre-line text-ink-soft">{objective.instruction}</p>
            {objective.plan_summary && (
              <>
                <h2 className="mt-4 text-sm font-semibold">Chief of Staff plan</h2>
                <p className="mt-1 text-[13.5px] text-ink-soft">{objective.plan_summary}</p>
              </>
            )}
            {objective.issues.map((issue) => (
              <p key={issue.message} className="mt-3 rounded-lg bg-danger-soft px-3 py-2 text-[13px] text-danger">
                {humanize(issue.type)} failed: {issue.message}
              </p>
            ))}
          </Card>
          {tasks.length === 0 ? (
            <Card>
              <EmptyState title={objective.status === "PLANNING" ? "Chief of Staff is planning…" : "No plan yet"} />
            </Card>
          ) : (
            <div className="grid gap-6 xl:grid-cols-[1fr_360px]">
              <Card className="min-w-0 p-5">
                <TaskGraph tasks={tasks} agents={agents.byId} selectedId={selected?.id} onSelect={(task) => setSelectedId(task.id)} />
              </Card>
              <TaskPanel task={selected} agents={agents.byId} objectiveId={objective.id} artifacts={data.artifacts} />
            </div>
          )}
        </div>
      )}

      {tab === "report" &&
        (objective.executive_summary ? (
          <ExecutiveReport
            summary={objective.executive_summary}
            reportHref={
              objective.executive_summary.report_artifact_id
                ? org.href(`/artifacts/${objective.executive_summary.report_artifact_id}`)
                : undefined
            }
          />
        ) : (
          <Card>
            <EmptyState title="The report is generated when the objective finishes" description="The Executive Reporter consolidates outcomes, failures and approvals." />
          </Card>
        ))}

      {tab === "communication" && <MessageList messages={data.messages} agents={agents.byId} />}

      {tab === "artifacts" && (
        <Card>
          {data.artifacts.length === 0 ? (
            <EmptyState title="No artifacts yet" />
          ) : (
            <ul className="divide-y divide-border">
              {data.artifacts.map((artifact) => (
                <li key={artifact.id}>
                  <Link href={org.href(`/artifacts/${artifact.id}`)} className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-surface-hover">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{artifact.title}</p>
                      <p className="text-xs text-muted">
                        {artifact.agent_id ? agents.byId.get(artifact.agent_id)?.name : "CEO"} · v{artifact.current_version} · {artifact.filename}
                      </p>
                    </div>
                    <StatusBadge status={artifact.review_status} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {tab === "approvals" && (
        <Card>
          {data.approvals.length === 0 ? (
            <EmptyState title="No approvals requested" description="Agents ask here before any external or risky action." />
          ) : (
            <ul className="divide-y divide-border">
              {data.approvals.map((approval) => (
                <li key={approval.id} className="flex items-center justify-between gap-3 px-5 py-3">
                  <div className="min-w-0">
                    <Link href={org.href(`/approvals/${approval.id}`)} className="text-sm font-medium hover:underline">
                      {approval.title}
                    </Link>
                    <p className="text-xs text-muted">
                      {dateTime(approval.created_at)}
                      {approval.execution_result?.status && ` · execution: ${approval.execution_result.status}`}
                    </p>
                  </div>
                  <StatusBadge status={approval.status} />
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {tab === "activity" && (
        <Card>
          <ActivityFeed events={data.activity} />
        </Card>
      )}
    </div>
  );
}

function TaskPanel({
  task,
  agents,
  objectiveId,
  artifacts,
}: {
  task: Task | null;
  agents: Map<string, Agent>;
  objectiveId: string;
  artifacts: Artifact[];
}) {
  const org = useOrg();
  const retry = useOrgMutation<string>((taskId) => ({ path: `/objectives/${objectiveId}/tasks/${taskId}/retry` }));
  if (!task) {
    return (
      <Card className="p-5 text-[13px] text-muted">Select a task in the plan to see its instructions, output, reviews and errors.</Card>
    );
  }
  const agent = task.assigned_agent_id ? agents.get(task.assigned_agent_id) : undefined;
  const taskArtifacts = artifacts.filter((artifact) => artifact.task_id === task.id);
  return (
    <Card className="space-y-4 p-5">
      <div>
        <StatusBadge status={task.status} />
        <h3 className="mt-2 text-[15px] font-semibold">{task.title}</h3>
        <p className="mt-0.5 text-xs text-muted">
          {agent ? (
            <Link href={org.href(`/agents/${agent.id}`)} className="hover:underline">
              {agent.name}
            </Link>
          ) : (
            task.role_key
          )}{" "}
          · {task.started_at ? `started ${clock(task.started_at)}` : "not started"}
          {task.completed_at && ` · ${duration(between(task.started_at, task.completed_at))}`}
        </p>
      </div>
      {task.error_message && (
        <div className="rounded-lg border border-danger/20 bg-danger-soft px-3 py-2 text-[13px]">
          <p className="font-medium text-danger">{humanize(task.error_category ?? "error")}</p>
          <p className="mt-0.5 text-ink-soft">{task.error_message}</p>
          {org.canEdit && ["FAILED", "BLOCKED"].includes(task.status) && (
            <Button size="sm" className="mt-2" onClick={() => retry.mutate(task.id)} loading={retry.isPending}>
              <RotateCcw className="size-3.5" /> Retry
            </Button>
          )}
          <FormError message={retry.error?.message} />
        </div>
      )}
      <Section title="Instructions">{task.instructions}</Section>
      {task.acceptance_criteria.length > 0 && (
        <Section title="Acceptance criteria">
          <ul className="list-disc pl-4">
            {task.acceptance_criteria.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </Section>
      )}
      {task.revision_count > 0 && (
        <Section title={`Review · ${task.revision_count} revision${task.revision_count > 1 ? "s" : ""}`}>{task.review_feedback}</Section>
      )}
      {task.output_summary && <Section title="Output">{task.output_summary}</Section>}
      {taskArtifacts.map((artifact) => (
        <Link
          key={artifact.id}
          href={org.href(`/artifacts/${artifact.id}`)}
          className="flex items-center justify-between rounded-lg border border-border px-3 py-2 text-[13px] hover:bg-surface-hover"
        >
          <span className="truncate">{artifact.title}</span>
          <ArrowRight className="size-3.5 shrink-0 text-muted" />
        </Link>
      ))}
      <p className="text-xs text-faint">
        Attempts {task.retry_count + 1}/{task.max_retries + 1}
        {task.execution_metadata.iteration_limit_reached ? " · iteration limit reached" : ""}
      </p>
    </Card>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="text-xs font-semibold tracking-wide text-muted uppercase">{title}</h4>
      <div className="mt-1 text-[13px] leading-relaxed whitespace-pre-line text-ink-soft">{children}</div>
    </div>
  );
}

const KIND_TONES = { handoff: "success", request: "info", feedback: "warning", delegation: "accent", info: "neutral" } as const;

function MessageList({ messages, agents }: { messages: AgentMessage[]; agents: Map<string, Agent> }) {
  if (!messages.length) {
    return (
      <Card>
        <EmptyState title="No messages yet" description="Assignments, handoffs, reviews and delegations between agents appear here." />
      </Card>
    );
  }
  return (
    <Card>
      <ol className="divide-y divide-border">
        {messages.map((message) => (
          <li key={message.id} className="px-5 py-3.5">
            <div className="flex flex-wrap items-center gap-2 text-[13px]">
              <span className="font-medium">{message.sender_agent_id ? agents.get(message.sender_agent_id)?.name : "System"}</span>
              <ArrowRight className="size-3 text-faint" />
              <span className="font-medium">{message.recipient_agent_id ? agents.get(message.recipient_agent_id)?.name : "—"}</span>
              <Badge tone={KIND_TONES[message.kind]}>{humanize(message.kind)}</Badge>
              <span className="ml-auto text-xs text-faint">{clock(message.created_at)}</span>
            </div>
            <p className="mt-1 text-[13.5px] font-medium text-ink">{message.subject}</p>
            <p className="mt-0.5 line-clamp-4 text-[13px] whitespace-pre-line text-ink-soft">{message.body}</p>
            {message.reason && <p className="mt-1 text-xs text-muted">Reason: {message.reason}</p>}
          </li>
        ))}
      </ol>
    </Card>
  );
}
