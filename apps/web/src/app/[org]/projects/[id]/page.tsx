"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { ActivityFeed } from "@/components/activity-feed";
import { StatusBadge } from "@/components/ui/badge";
import { LinkButton } from "@/components/ui/button";
import { Card, CardHeader, PageHeader, Stat } from "@/components/ui/card";
import { Avatar, EmptyState, ErrorState, PageSkeleton, Progress } from "@/components/ui/feedback";
import { useOrg, useOrgQuery } from "@/lib/session";
import type { ActivityEvent, Agent, Artifact, Objective, Project, Task } from "@/lib/types";

interface ProjectDetail {
  project: Project;
  objectives: Objective[];
  agents: Agent[];
  tasks: Task[];
  artifacts: Artifact[];
  documents: { id: string; title: string; chunk_count: number }[];
  activity: ActivityEvent[];
  decisions: ActivityEvent[];
  metrics: { tasks_total: number; tasks_completed: number };
}

export default function ProjectPage() {
  const org = useOrg();
  const { id } = useParams<{ id: string }>();
  const { data, error, isPending } = useOrgQuery<ProjectDetail>(["project", id], `/projects/${id}`);
  if (isPending) return <PageSkeleton />;
  if (error) return <ErrorState error={error} />;
  const { project, metrics } = data;
  const progress = metrics.tasks_total ? Math.round((metrics.tasks_completed / metrics.tasks_total) * 100) : 0;

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow={<Link href={org.href("/projects")} className="hover:text-ink">Projects</Link>}
        title={project.name}
        description={project.description}
        actions={
          org.canEdit && (
            <LinkButton href={org.href("/objectives/new")} variant="primary">
              <Plus className="size-4" /> New objective
            </LinkButton>
          )
        }
      />
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Objectives" value={data.objectives.length} />
        <Stat label="Agents involved" value={data.agents.length} />
        <Stat label="Tasks completed" value={`${metrics.tasks_completed}/${metrics.tasks_total}`} />
        <Stat label="Artifacts" value={data.artifacts.length} />
      </div>
      <Card className="p-5">
        <div className="mb-2 flex justify-between text-[13px]">
          <span className="font-medium">Progress</span>
          <span className="text-muted">
            <StatusBadge status={project.status} /> {project.target_date && `· due ${project.target_date}`}
          </span>
        </div>
        <Progress value={progress} />
      </Card>
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <CardHeader title="Objectives" />
            {data.objectives.length === 0 ? (
              <EmptyState title="No objectives in this project" description="Choose this project when creating an objective." />
            ) : (
              <ul className="divide-y divide-border border-t border-border">
                {data.objectives.map((objective) => (
                  <li key={objective.id}>
                    <Link href={org.href(`/objectives/${objective.id}`)} className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-surface-hover">
                      <span className="truncate text-sm font-medium">{objective.title}</span>
                      <StatusBadge status={objective.status} />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card>
            <CardHeader title="Decisions" description="CEO approvals and rejections in this project" />
            <div className="border-t border-border">
              <ActivityFeed events={data.decisions} empty="No decisions yet" />
            </div>
          </Card>
          <Card>
            <CardHeader title="Activity" />
            <div className="border-t border-border">
              <ActivityFeed events={data.activity} compact />
            </div>
          </Card>
        </div>
        <div className="space-y-6">
          <Card>
            <CardHeader title="Team" />
            <ul className="divide-y divide-border border-t border-border">
              {data.agents.length === 0 && <li className="px-5 py-3 text-[13px] text-muted">No agents yet</li>}
              {data.agents.map((agent) => (
                <li key={agent.id}>
                  <Link href={org.href(`/agents/${agent.id}`)} className="flex items-center gap-3 px-5 py-2.5 hover:bg-surface-hover">
                    <Avatar name={agent.name} className="size-7" />
                    <span className="text-[13.5px]">{agent.name}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
          <Card>
            <CardHeader title="Artifacts" />
            <ul className="divide-y divide-border border-t border-border">
              {data.artifacts.length === 0 && <li className="px-5 py-3 text-[13px] text-muted">No artifacts yet</li>}
              {data.artifacts.map((artifact) => (
                <li key={artifact.id}>
                  <Link href={org.href(`/artifacts/${artifact.id}`)} className="block truncate px-5 py-2.5 text-[13.5px] hover:bg-surface-hover">
                    {artifact.title}
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
          <Card>
            <CardHeader title="Knowledge" />
            <ul className="divide-y divide-border border-t border-border">
              {data.documents.length === 0 && <li className="px-5 py-3 text-[13px] text-muted">No project documents</li>}
              {data.documents.map((document) => (
                <li key={document.id} className="px-5 py-2.5 text-[13.5px]">
                  {document.title}
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}
