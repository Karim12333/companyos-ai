"use client";

import { AlertOctagon, ArrowRight, Plus } from "lucide-react";
import Link from "next/link";

import { ActivityFeed } from "@/components/activity-feed";
import { ApprovalActions } from "@/components/approval-actions";
import { RiskBadge, StatusBadge } from "@/components/ui/badge";
import { LinkButton } from "@/components/ui/button";
import { Card, CardHeader, Stat } from "@/components/ui/card";
import { EmptyState, ErrorState, PageSkeleton, Progress } from "@/components/ui/feedback";
import { duration, between, timeAgo } from "@/lib/format";
import { useOrg, useOrgQuery } from "@/lib/session";
import type { ActivityEvent, Approval, Department, Objective, TaskStatus } from "@/lib/types";

interface Headquarters {
  ceo_name: string;
  health: { active_objectives: number; agents_working: number; tasks_completed_today: number; waiting_for_approval: number };
  departments: Department[];
  live: {
    agent_id: string;
    agent_name: string;
    agent_title: string;
    task_id: string;
    task_title: string;
    task_status: TaskStatus;
    objective_id: string;
    objective_title: string;
    started_at: string | null;
  }[];
  attention: { approvals: Approval[]; failures: { id: string; title: string; summary: string; link: string | null; created_at: string }[] };
  objectives: Objective[];
  activity: ActivityEvent[];
}

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  return hour < 18 ? "Good afternoon" : "Good evening";
}

export default function HeadquartersPage() {
  const org = useOrg();
  const { data, error, isPending } = useOrgQuery<Headquarters>(["headquarters"], "/headquarters", { refetchInterval: 15_000 });

  if (isPending) return <PageSkeleton />;
  if (error) return <ErrorState error={error} />;

  const attentionCount = data.attention.approvals.length + data.attention.failures.length;
  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-[13px] text-muted">{new Date().toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" })}</p>
          <h1 className="mt-0.5 text-[26px] font-semibold tracking-tight">
            {greeting()}, {data.ceo_name}
          </h1>
        </div>
        {org.canEdit && (
          <LinkButton href={org.href("/objectives/new")} variant="primary">
            <Plus className="size-4" /> New objective
          </LinkButton>
        )}
      </div>

      <section aria-label="Organization health" className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Active objectives" value={data.health.active_objectives} />
        <Stat label="Agents working" value={data.health.agents_working} tone={data.health.agents_working ? "accent" : undefined} />
        <Stat label="Tasks completed today" value={data.health.tasks_completed_today} />
        <Stat
          label="Waiting for approval"
          value={data.health.waiting_for_approval}
          tone={data.health.waiting_for_approval ? "warning" : undefined}
        />
      </section>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <CardHeader
              title="Your attention"
              description={attentionCount ? `${attentionCount} item${attentionCount > 1 ? "s" : ""} need you` : "Nothing needs you right now"}
              action={
                <Link href={org.href("/inbox")} className="text-[13px] text-muted hover:text-ink">
                  Open inbox
                </Link>
              }
            />
            {attentionCount === 0 ? (
              <EmptyState title="All clear" description="Approvals and failures will surface here." />
            ) : (
              <ul className="divide-y divide-border border-t border-border">
                {data.attention.approvals.map((approval) => (
                  <li key={approval.id} className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <Link href={org.href(`/approvals/${approval.id}`)} className="text-sm font-medium hover:underline">
                          {approval.title}
                        </Link>
                        <RiskBadge level={approval.risk_level} />
                      </div>
                      <p className="mt-1 line-clamp-2 text-[13px] text-muted">{approval.summary}</p>
                    </div>
                    <ApprovalActions approval={approval} />
                  </li>
                ))}
                {data.attention.failures.map((failure) => (
                  <li key={failure.id} className="flex items-start gap-3 px-5 py-4">
                    <AlertOctagon className="mt-0.5 size-4 shrink-0 text-danger" />
                    <div className="min-w-0 flex-1">
                      <Link href={failure.link ? org.href(failure.link) : org.href("/inbox")} className="text-sm font-medium hover:underline">
                        {failure.title}
                      </Link>
                      <p className="mt-0.5 line-clamp-2 text-[13px] text-muted">{failure.summary}</p>
                    </div>
                    <span className="text-xs text-faint">{timeAgo(failure.created_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card>
            <CardHeader title="Live activity" description="What your agents are doing right now" />
            {data.live.length === 0 ? (
              <EmptyState title="No agents working" description="Start an objective and watch your organization work." />
            ) : (
              <ul className="divide-y divide-border border-t border-border">
                {data.live.map((item) => (
                  <li key={item.task_id} className="flex items-center gap-4 px-5 py-3">
                    <div className="min-w-0 flex-1">
                      <Link href={org.href(`/agents/${item.agent_id}`)} className="text-sm font-medium hover:underline">
                        {item.agent_name}
                      </Link>
                      <p className="truncate text-[13px] text-muted">
                        {item.task_title} · <Link href={org.href(`/objectives/${item.objective_id}`)} className="hover:underline">{item.objective_title}</Link>
                      </p>
                    </div>
                    <span className="hidden text-xs text-faint tabular-nums sm:block">{duration(between(item.started_at, null))}</span>
                    <StatusBadge status={item.task_status} />
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card>
            <CardHeader
              title="Objectives"
              action={
                <Link href={org.href("/objectives")} className="flex items-center gap-1 text-[13px] text-muted hover:text-ink">
                  All objectives <ArrowRight className="size-3.5" />
                </Link>
              }
            />
            {data.objectives.length === 0 ? (
              <EmptyState
                title="No objectives yet"
                description="Give your organization its first business objective."
                action={org.canEdit && <LinkButton href={org.href("/objectives/new")} size="sm">Create objective</LinkButton>}
              />
            ) : (
              <ul className="divide-y divide-border border-t border-border">
                {data.objectives.map((objective) => (
                  <li key={objective.id}>
                    <Link href={org.href(`/objectives/${objective.id}`)} className="flex items-center gap-4 px-5 py-3 hover:bg-surface-hover">
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">{objective.title}</p>
                        <p className="text-xs text-muted">{objective.current_stage} · {timeAgo(objective.created_at)}</p>
                      </div>
                      <div className="hidden w-28 sm:block">
                        <Progress value={objective.progress} tone={objective.status === "COMPLETED" ? "success" : "accent"} />
                      </div>
                      <StatusBadge status={objective.status} />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader title="Departments" />
            <ul className="divide-y divide-border border-t border-border">
              {data.departments.map((department) => (
                <li key={department.id}>
                  <Link href={org.href(`/departments/${department.id}`)} className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-surface-hover">
                    <div>
                      <p className="text-sm font-medium">{department.name}</p>
                      <p className="text-xs text-muted">
                        {department.agent_count} agents · {department.active_tasks} active
                      </p>
                    </div>
                    <StatusBadge status={department.status ?? "idle"} />
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
          <Card>
            <CardHeader
              title="Recent activity"
              action={
                <Link href={org.href("/activity")} className="text-[13px] text-muted hover:text-ink">
                  View all
                </Link>
              }
            />
            <div className="border-t border-border">
              <ActivityFeed events={data.activity} compact />
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
