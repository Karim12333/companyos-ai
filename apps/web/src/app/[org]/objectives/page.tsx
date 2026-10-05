"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { StatusBadge } from "@/components/ui/badge";
import { LinkButton } from "@/components/ui/button";
import { Card, PageHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, PageSkeleton, Progress } from "@/components/ui/feedback";
import { Tabs } from "@/components/ui/tabs";
import { dateTime, usd } from "@/lib/format";
import { useOrg, useOrgQuery } from "@/lib/session";
import type { Objective } from "@/lib/types";

type Filter = "all" | "active" | "WAITING_FOR_APPROVAL" | "COMPLETED" | "FAILED";

export default function ObjectivesPage() {
  const org = useOrg();
  const [filter, setFilter] = useState<Filter>("all");
  const query = filter === "all" ? "" : `?status=${filter}`;
  const { data, error, isPending } = useOrgQuery<Objective[]>(["objectives", filter], `/objectives${query}`);

  return (
    <div>
      <PageHeader
        title="Objectives"
        description="Major outcomes your organization is working on."
        actions={
          org.canEdit && (
            <LinkButton href={org.href("/objectives/new")} variant="primary">
              <Plus className="size-4" /> New objective
            </LinkButton>
          )
        }
      />
      <Tabs<Filter>
        value={filter}
        onChange={setFilter}
        tabs={[
          { value: "all", label: "All" },
          { value: "active", label: "In progress" },
          { value: "WAITING_FOR_APPROVAL", label: "Awaiting approval" },
          { value: "COMPLETED", label: "Completed" },
          { value: "FAILED", label: "Failed" },
        ]}
      />
      <div className="mt-4">
        {isPending ? (
          <PageSkeleton />
        ) : error ? (
          <ErrorState error={error} />
        ) : data.length === 0 ? (
          <Card>
            <EmptyState title="No objectives here" description="Objectives you create will appear in this list." />
          </Card>
        ) : (
          <Card className="overflow-hidden">
            <table className="w-full text-sm">
              <thead className="border-b border-border bg-surface-muted text-left text-xs text-muted">
                <tr>
                  <th className="px-5 py-2.5 font-medium">Objective</th>
                  <th className="hidden px-3 py-2.5 font-medium md:table-cell">Progress</th>
                  <th className="hidden px-3 py-2.5 font-medium lg:table-cell">Created</th>
                  <th className="hidden px-3 py-2.5 font-medium lg:table-cell">Cost</th>
                  <th className="px-5 py-2.5 text-right font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {data.map((objective) => (
                  <tr key={objective.id} className="hover:bg-surface-hover">
                    <td className="max-w-0 px-5 py-3">
                      <Link href={org.href(`/objectives/${objective.id}`)} className="block truncate font-medium hover:underline">
                        {objective.title}
                      </Link>
                      <span className="text-xs text-muted">{objective.current_stage}</span>
                    </td>
                    <td className="hidden w-40 px-3 md:table-cell">
                      <Progress value={objective.progress} tone={objective.status === "COMPLETED" ? "success" : "accent"} />
                    </td>
                    <td className="hidden px-3 text-muted lg:table-cell">{dateTime(objective.created_at)}</td>
                    <td className="hidden px-3 text-muted tabular-nums lg:table-cell">{usd(objective.cost_usd)}</td>
                    <td className="px-5 text-right">
                      <StatusBadge status={objective.status} />
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
