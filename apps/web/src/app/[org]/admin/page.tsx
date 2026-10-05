"use client";

import { useQuery } from "@tanstack/react-query";

import { Badge, StatusBadge } from "@/components/ui/badge";
import { Card, CardHeader, PageHeader, Stat } from "@/components/ui/card";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/ui/feedback";
import { api } from "@/lib/api";
import { dateTime, usd } from "@/lib/format";

interface Overview {
  health: Record<string, string>;
  totals: { organizations: number; users: number; objectives: number; running_workflows: number; failed_tasks: number; cost_30d_usd: number };
  organizations: { id: string; name: string; slug: string; plan: string; status: string; members: number; objectives: number; cost_30d_usd: number; created_at: string }[];
  workflow_failures: { objective_id: string; title: string; status: string; organization_id: string; completed_at: string | null }[];
  failed_notifications: { id: string; kind: string; recipient: string; error: string | null; created_at: string }[];
  audit: { id: string; action: string; organization_id: string | null; outcome: string; created_at: string }[];
}

export default function PlatformAdminPage() {
  const { data, error, isPending } = useQuery({ queryKey: ["platform"], queryFn: () => api<Overview>("/platform/overview") });
  if (isPending) return <PageSkeleton />;
  if (error) return <ErrorState error={error} />;
  return (
    <div className="space-y-6">
      <PageHeader title="Platform administration" description="SaaS-wide health, tenants, usage and failures. Visible to platform administrators only." />
      <Card className="flex flex-wrap gap-3 px-5 py-4">
        {Object.entries(data.health).map(([name, status]) => (
          <span key={name} className="flex items-center gap-2 text-[13px]">
            <span className="capitalize">{name}</span>
            <Badge tone={status === "ok" ? "success" : "danger"}>{status}</Badge>
          </span>
        ))}
      </Card>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-6">
        <Stat label="Organizations" value={data.totals.organizations} />
        <Stat label="Users" value={data.totals.users} />
        <Stat label="Objectives" value={data.totals.objectives} />
        <Stat label="Running workflows" value={data.totals.running_workflows} />
        <Stat label="Failed tasks" value={data.totals.failed_tasks} />
        <Stat label="AI cost (30d)" value={usd(data.totals.cost_30d_usd, 2)} />
      </div>
      <Card className="overflow-x-auto">
        <CardHeader title="Organizations" />
        <table className="w-full text-[13px]">
          <thead className="border-y border-border bg-surface-muted text-left text-xs text-muted">
            <tr>
              <th className="px-5 py-2 font-medium">Name</th>
              <th className="px-3 py-2 font-medium">Plan</th>
              <th className="px-3 py-2 font-medium">Members</th>
              <th className="px-3 py-2 font-medium">Objectives</th>
              <th className="px-3 py-2 font-medium">Cost 30d</th>
              <th className="px-5 py-2 font-medium">Created</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {data.organizations.map((organization) => (
              <tr key={organization.id}>
                <td className="px-5 py-2.5 font-medium">{organization.name}</td>
                <td className="px-3">
                  <Badge>{organization.plan}</Badge>
                </td>
                <td className="px-3 tabular-nums">{organization.members}</td>
                <td className="px-3 tabular-nums">{organization.objectives}</td>
                <td className="px-3 tabular-nums">{usd(organization.cost_30d_usd)}</td>
                <td className="px-5 text-muted">{dateTime(organization.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Objective failures" />
          {data.workflow_failures.length === 0 ? (
            <EmptyState title="No failed objectives" />
          ) : (
            <ul className="divide-y divide-border border-t border-border">
              {data.workflow_failures.map((failure) => (
                <li key={failure.objective_id} className="flex items-center justify-between gap-3 px-5 py-2.5 text-[13px]">
                  <span className="truncate">{failure.title}</span>
                  <StatusBadge status={failure.status} />
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card>
          <CardHeader title="Failed notifications" />
          {data.failed_notifications.length === 0 ? (
            <EmptyState title="All emails delivered" />
          ) : (
            <ul className="divide-y divide-border border-t border-border">
              {data.failed_notifications.map((item) => (
                <li key={item.id} className="px-5 py-2.5 text-[13px]">
                  <p>
                    {item.kind} → {item.recipient}
                  </p>
                  <p className="text-xs text-danger">{item.error}</p>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
