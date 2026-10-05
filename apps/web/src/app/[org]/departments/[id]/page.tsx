"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { ActivityFeed } from "@/components/activity-feed";
import { StatusBadge } from "@/components/ui/badge";
import { Card, CardHeader, PageHeader, Stat } from "@/components/ui/card";
import { Avatar, EmptyState, ErrorState, PageSkeleton } from "@/components/ui/feedback";
import { duration, timeAgo } from "@/lib/format";
import { useOrg, useOrgQuery } from "@/lib/session";
import type { ActivityEvent, Agent, Artifact, Department, Objective, Task } from "@/lib/types";

interface DepartmentDetail {
  department: Department;
  agents: Agent[];
  objectives: Objective[];
  active_tasks: Task[];
  recent_completed: Task[];
  failures: Task[];
  artifacts: Artifact[];
  activity: ActivityEvent[];
  metrics: { tasks_total: number; tasks_completed: number; tasks_failed: number; average_task_seconds: number | null };
}

function TaskList({ tasks, empty }: { tasks: Task[]; empty: string }) {
  const org = useOrg();
  if (!tasks.length) return <EmptyState title={empty} />;
  return (
    <ul className="divide-y divide-border border-t border-border">
      {tasks.map((task) => (
        <li key={task.id}>
          <Link href={org.href(`/objectives/${task.objective_id}?task=${task.id}`)} className="flex items-center justify-between gap-3 px-5 py-2.5 hover:bg-surface-hover">
            <span className="truncate text-[13.5px]">{task.title}</span>
            <StatusBadge status={task.status} />
          </Link>
        </li>
      ))}
    </ul>
  );
}

export default function DepartmentPage() {
  const org = useOrg();
  const { id } = useParams<{ id: string }>();
  const { data, error, isPending } = useOrgQuery<DepartmentDetail>(["department", id], `/departments/${id}`);
  if (isPending) return <PageSkeleton />;
  if (error) return <ErrorState error={error} />;
  const manager = data.agents.find((agent) => agent.id === data.department.manager_agent_id);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={<Link href={org.href("/departments")} className="hover:text-ink">Departments</Link>}
        title={data.department.name}
        description={data.department.description}
      />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Agents" value={data.agents.length} />
        <Stat label="Tasks completed" value={data.metrics.tasks_completed} />
        <Stat label="Failed" value={data.metrics.tasks_failed} />
        <Stat label="Avg. task time" value={duration(data.metrics.average_task_seconds)} />
      </div>
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <CardHeader title="Team" description={manager ? `Managed by ${manager.name}` : undefined} />
            <ul className="divide-y divide-border border-t border-border">
              {data.agents.map((agent) => (
                <li key={agent.id}>
                  <Link href={org.href(`/agents/${agent.id}`)} className="flex items-center gap-3 px-5 py-3 hover:bg-surface-hover">
                    <Avatar name={agent.name} />
                    <div className="min-w-0 flex-1">
                      <p className="text-sm font-medium">{agent.name}</p>
                      <p className="truncate text-xs text-muted">{agent.title}</p>
                    </div>
                    <StatusBadge status={agent.status} />
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
          <Card>
            <CardHeader title="Active tasks" />
            <TaskList tasks={data.active_tasks} empty="No active tasks" />
          </Card>
          <Card>
            <CardHeader title="Recently completed" />
            <TaskList tasks={data.recent_completed} empty="Nothing completed yet" />
          </Card>
          {data.failures.length > 0 && (
            <Card>
              <CardHeader title="Failures" />
              <TaskList tasks={data.failures} empty="" />
            </Card>
          )}
        </div>
        <div className="space-y-6">
          <Card>
            <CardHeader title="Objectives" />
            {data.objectives.length === 0 ? (
              <EmptyState title="Not involved in any objective yet" />
            ) : (
              <ul className="divide-y divide-border border-t border-border">
                {data.objectives.map((objective) => (
                  <li key={objective.id}>
                    <Link href={org.href(`/objectives/${objective.id}`)} className="flex items-center justify-between gap-2 px-5 py-2.5 hover:bg-surface-hover">
                      <span className="truncate text-[13.5px]">{objective.title}</span>
                      <StatusBadge status={objective.status} />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card>
            <CardHeader title="Artifacts" />
            {data.artifacts.length === 0 ? (
              <EmptyState title="No artifacts yet" />
            ) : (
              <ul className="divide-y divide-border border-t border-border">
                {data.artifacts.map((artifact) => (
                  <li key={artifact.id}>
                    <Link href={org.href(`/artifacts/${artifact.id}`)} className="block px-5 py-2.5 hover:bg-surface-hover">
                      <p className="truncate text-[13.5px]">{artifact.title}</p>
                      <p className="text-xs text-muted">{timeAgo(artifact.updated_at)}</p>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card>
            <CardHeader title="Activity" />
            <div className="border-t border-border">
              <ActivityFeed events={data.activity} compact />
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
