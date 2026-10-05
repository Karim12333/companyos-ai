"use client";

import Link from "next/link";
import { useState } from "react";

import { StatusBadge } from "@/components/ui/badge";
import { Card, PageHeader } from "@/components/ui/card";
import { Avatar, ErrorState, PageSkeleton } from "@/components/ui/feedback";
import { Tabs } from "@/components/ui/tabs";
import { cn } from "@/lib/format";
import { useAgents, useDepartments } from "@/lib/hooks";
import { useOrg } from "@/lib/session";
import type { Agent } from "@/lib/types";

type View = "chart" | "list";

function AgentNode({ agent, departmentName }: { agent: Agent; departmentName?: string }) {
  const org = useOrg();
  return (
    <Link
      href={org.href(`/agents/${agent.id}`)}
      className={cn(
        "flex items-center gap-2.5 rounded-lg border border-border bg-surface px-3 py-2 shadow-card hover:border-border-strong",
        !agent.is_active && "opacity-50",
      )}
    >
      <Avatar name={agent.name} className="size-7" />
      <span className="min-w-0">
        <span className="block truncate text-[13px] font-medium">{agent.name}</span>
        <span className="block truncate text-[11px] text-muted">{departmentName ?? agent.title}</span>
      </span>
      {agent.status === "working" && <span className="live-dot ml-1 size-1.5 shrink-0 rounded-full bg-info" aria-label="Working" />}
    </Link>
  );
}

function Branch({ agent, reportsByManager, departments }: { agent: Agent; reportsByManager: Map<string, Agent[]>; departments: Map<string, string> }) {
  const reports = reportsByManager.get(agent.id) ?? [];
  return (
    <li className="relative">
      <AgentNode agent={agent} departmentName={agent.department_id ? departments.get(agent.department_id) : undefined} />
      {reports.length > 0 && (
        <ul className="mt-2 ml-4 space-y-2 border-l border-border pl-5">
          {reports.map((report) => (
            <Branch key={report.id} agent={report} reportsByManager={reportsByManager} departments={departments} />
          ))}
        </ul>
      )}
    </li>
  );
}

export default function AgentsPage() {
  const org = useOrg();
  const [view, setView] = useState<View>("chart");
  const { data, error, isPending } = useAgents();
  const departments = useDepartments();
  if (isPending) return <PageSkeleton />;
  if (error) return <ErrorState error={error} />;

  const departmentNames = new Map((departments.data ?? []).map((department) => [department.id, department.name]));
  const children = new Map<string, Agent[]>();
  data.forEach((agent) => {
    if (agent.manager_agent_id) children.set(agent.manager_agent_id, [...(children.get(agent.manager_agent_id) ?? []), agent]);
  });
  const roots = data.filter((agent) => !agent.manager_agent_id);

  return (
    <div>
      <PageHeader title="Agents" description="Your AI team. Reporting lines and delegation rights are configuration, enforced by the platform." />
      <Tabs<View> value={view} onChange={setView} tabs={[{ value: "chart", label: "Organization" }, { value: "list", label: "All agents", count: data.length }]} />
      <div className="mt-4">
        {view === "chart" ? (
          <Card className="overflow-x-auto p-6">
            <div className="mb-4 inline-flex items-center gap-2 rounded-lg border border-dashed border-border-strong px-3 py-2 text-[13px] font-medium">
              CEO <span className="text-muted">· you</span>
            </div>
            <ul className="ml-4 space-y-2 border-l border-border pl-5">
              {roots.map((agent) => (
                <Branch key={agent.id} agent={agent} reportsByManager={children} departments={departmentNames} />
              ))}
            </ul>
          </Card>
        ) : (
          <Card className="overflow-hidden">
            <table className="w-full text-sm">
              <thead className="border-b border-border bg-surface-muted text-left text-xs text-muted">
                <tr>
                  <th className="px-5 py-2.5 font-medium">Agent</th>
                  <th className="hidden px-3 py-2.5 font-medium sm:table-cell">Department</th>
                  <th className="hidden px-3 py-2.5 font-medium md:table-cell">Reports to</th>
                  <th className="px-5 py-2.5 text-right font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {data.map((agent) => (
                  <tr key={agent.id} className="hover:bg-surface-hover">
                    <td className="px-5 py-3">
                      <Link href={org.href(`/agents/${agent.id}`)} className="font-medium hover:underline">
                        {agent.name}
                      </Link>
                      <p className="text-xs text-muted">{agent.title}</p>
                    </td>
                    <td className="hidden px-3 text-muted sm:table-cell">{agent.department_id ? departmentNames.get(agent.department_id) : "—"}</td>
                    <td className="hidden px-3 text-muted md:table-cell">
                      {agent.manager_agent_id ? data.find((item) => item.id === agent.manager_agent_id)?.name : "CEO"}
                    </td>
                    <td className="px-5 text-right">
                      <StatusBadge status={agent.is_active ? agent.status : "disabled"} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </div>
    </div>
  );
}
