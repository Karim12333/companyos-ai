"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { ApprovalActions } from "@/components/approval-actions";
import { RiskBadge, StatusBadge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { ErrorState, PageSkeleton } from "@/components/ui/feedback";
import { dateTime, humanize } from "@/lib/format";
import { useAgents } from "@/lib/hooks";
import { useOrg, useOrgQuery } from "@/lib/session";
import type { Approval, Artifact } from "@/lib/types";

interface ApprovalDetail {
  approval: Approval;
  objective: { id: string; title: string } | null;
  task: { id: string; title: string; status: string } | null;
  artifacts: Artifact[];
}

export default function ApprovalPage() {
  const org = useOrg();
  const { id } = useParams<{ id: string }>();
  const agents = useAgents();
  const { data, error, isPending } = useOrgQuery<ApprovalDetail>(["approval", id], `/approvals/${id}`);

  if (isPending) return <PageSkeleton />;
  if (error) return <ErrorState error={error} />;
  const { approval } = data;
  const agent = approval.agent_id ? agents.byId.get(approval.agent_id) : undefined;
  const args = approval.payload.arguments ?? {};

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div>
        <Link href={org.href("/inbox")} className="text-[13px] text-muted hover:text-ink">
          CEO Inbox
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <h1 className="text-[22px] font-semibold tracking-tight">{approval.title}</h1>
          <StatusBadge status={approval.status} />
        </div>
        <p className="mt-1 text-sm text-muted">
          Requested by {agent?.name ?? "an agent"} · {dateTime(approval.created_at)}
          {data.objective && (
            <>
              {" · "}
              <Link href={org.href(`/objectives/${data.objective.id}`)} className="hover:underline">
                {data.objective.title}
              </Link>
            </>
          )}
        </p>
      </div>

      <Card>
        <CardHeader title="Requested action" action={<RiskBadge level={approval.risk_level} />} />
        <div className="space-y-4 border-t border-border px-5 py-4">
          <dl className="grid gap-3 text-[13.5px] sm:grid-cols-[140px_1fr]">
            <dt className="text-muted">Action</dt>
            <dd className="font-medium">{humanize(approval.action_key)}</dd>
            {Object.entries(args).map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="text-muted">{humanize(key)}</dt>
                <dd className="rounded-lg bg-surface-muted px-3 py-2 whitespace-pre-wrap">{String(value)}</dd>
              </div>
            ))}
            {approval.payload.reason && (
              <>
                <dt className="text-muted">Why approval</dt>
                <dd>{approval.payload.reason}</dd>
              </>
            )}
          </dl>
          {approval.status === "PENDING" ? (
            <div className="border-t border-border pt-4">
              <p className="mb-3 text-[13px] text-muted">
                Nothing happens until you decide. Approving executes this exact action through the policy-checked tool gateway.
              </p>
              <ApprovalActions approval={approval} withNote />
            </div>
          ) : (
            <div className="rounded-lg bg-surface-muted px-4 py-3 text-[13px]">
              <p>
                <span className="font-medium">{humanize(approval.status)}</span> {dateTime(approval.decided_at)}
                {approval.decision_note && ` — “${approval.decision_note}”`}
              </p>
              {approval.execution_result && (
                <p className="mt-1 text-muted">
                  Execution: {approval.execution_result.status} {approval.execution_result.message && `· ${approval.execution_result.message}`}
                </p>
              )}
            </div>
          )}
        </div>
      </Card>

      {data.artifacts.length > 0 && (
        <Card>
          <CardHeader title="Related deliverables" description="Preview the work behind this request before deciding." />
          <ul className="divide-y divide-border border-t border-border">
            {data.artifacts.map((artifact) => (
              <li key={artifact.id}>
                <Link href={org.href(`/artifacts/${artifact.id}`)} className="flex items-center justify-between px-5 py-3 text-sm hover:bg-surface-hover">
                  {artifact.title}
                  <span className="text-xs text-muted">v{artifact.current_version}</span>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
