"use client";

import { useState } from "react";

import { ActivityFeed } from "@/components/activity-feed";
import { Card, PageHeader } from "@/components/ui/card";
import { ErrorState, PageSkeleton } from "@/components/ui/feedback";
import { Select } from "@/components/ui/form";
import { useAgents, useDepartments } from "@/lib/hooks";
import { useOrgQuery } from "@/lib/session";
import type { ActivityEvent, Objective } from "@/lib/types";

const EVENT_TYPES = [
  ["", "All events"],
  ["objective.", "Objectives"],
  ["task.", "Tasks"],
  ["review.", "Reviews"],
  ["approval.", "Approvals"],
  ["artifact.", "Artifacts"],
  ["message.", "Messages"],
  ["integration.", "Integrations"],
];

export default function ActivityPage() {
  const agents = useAgents();
  const departments = useDepartments();
  const { data: objectives } = useOrgQuery<Objective[]>(["objectives", "all"], "/objectives");
  const [filters, setFilters] = useState({ objective_id: "", department_id: "", agent_id: "", event_type: "" });
  const query = new URLSearchParams(Object.entries(filters).filter(([, value]) => value)).toString();
  const { data, error, isPending } = useOrgQuery<ActivityEvent[]>(["activity", query], `/activity?limit=200&${query}`);
  const set = (key: keyof typeof filters) => (event: React.ChangeEvent<HTMLSelectElement>) =>
    setFilters((current) => ({ ...current, [key]: event.target.value }));

  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title="Activity" description="The complete, human-readable history of your organization." />
      <div className="mb-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        <Select aria-label="Objective" value={filters.objective_id} onChange={set("objective_id")}>
          <option value="">All objectives</option>
          {objectives?.map((objective) => (
            <option key={objective.id} value={objective.id}>
              {objective.title}
            </option>
          ))}
        </Select>
        <Select aria-label="Department" value={filters.department_id} onChange={set("department_id")}>
          <option value="">All departments</option>
          {departments.data?.map((department) => (
            <option key={department.id} value={department.id}>
              {department.name}
            </option>
          ))}
        </Select>
        <Select aria-label="Agent" value={filters.agent_id} onChange={set("agent_id")}>
          <option value="">All agents</option>
          {agents.data?.map((agent) => (
            <option key={agent.id} value={agent.id}>
              {agent.name}
            </option>
          ))}
        </Select>
        <Select aria-label="Event type" value={filters.event_type} onChange={set("event_type")}>
          {EVENT_TYPES.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </Select>
      </div>
      {isPending ? <PageSkeleton /> : error ? <ErrorState error={error} /> : <Card><ActivityFeed events={data} /></Card>}
    </div>
  );
}
