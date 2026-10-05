"use client";

import Link from "next/link";

import { StatusBadge } from "@/components/ui/badge";
import { Card, PageHeader } from "@/components/ui/card";
import { ErrorState, PageSkeleton } from "@/components/ui/feedback";
import { useDepartments } from "@/lib/hooks";
import { useOrg } from "@/lib/session";

export default function DepartmentsPage() {
  const org = useOrg();
  const { data, error, isPending } = useDepartments();
  if (isPending) return <PageSkeleton />;
  if (error) return <ErrorState error={error} />;
  return (
    <div>
      <PageHeader title="Departments" description="How your organization is structured and what each team is doing." />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {data.map((department) => (
          <Link key={department.id} href={org.href(`/departments/${department.id}`)}>
            <Card className="h-full p-5 transition-colors hover:border-border-strong">
              <div className="flex items-start justify-between gap-3">
                <h2 className="text-[15px] font-semibold">{department.name}</h2>
                <StatusBadge status={department.active_tasks ? "active" : "idle"} />
              </div>
              <p className="mt-1 line-clamp-2 text-[13px] text-muted">{department.description}</p>
              <dl className="mt-4 grid grid-cols-3 gap-2 border-t border-border pt-3 text-center">
                <div>
                  <dt className="text-[11px] text-muted">Agents</dt>
                  <dd className="text-lg font-semibold tabular-nums">{department.agent_count}</dd>
                </div>
                <div>
                  <dt className="text-[11px] text-muted">Active tasks</dt>
                  <dd className="text-lg font-semibold tabular-nums">{department.active_tasks}</dd>
                </div>
                <div>
                  <dt className="text-[11px] text-muted">Completed</dt>
                  <dd className="text-lg font-semibold tabular-nums">{department.completed_tasks}</dd>
                </div>
              </dl>
              {department.manager_name && <p className="mt-3 text-xs text-muted">Led by {department.manager_name}</p>}
            </Card>
          </Link>
        ))}
      </div>
    </div>
  );
}
