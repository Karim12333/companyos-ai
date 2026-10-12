"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";

import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { ErrorState, PageSkeleton } from "@/components/ui/feedback";
import { FormError, Textarea } from "@/components/ui/form";
import { cn, dateTime, humanize } from "@/lib/format";
import { useAgents, useOrgMutation } from "@/lib/hooks";
import { useOrg, useOrgQuery } from "@/lib/session";
import type { Artifact } from "@/lib/types";

interface EscalationOption {
  key: string;
  label: string;
  description: string;
  requires_note: boolean;
}

interface EscalationDetail {
  escalation: {
    id: string;
    kind: string;
    question: string;
    context: string;
    options: EscalationOption[];
    status: "OPEN" | "RESOLVED" | "CANCELLED";
    resolution_option: string | null;
    resolution_note: string;
    resolved_at: string | null;
    agent_id: string | null;
    created_at: string;
  };
  objective: { id: string; title: string } | null;
  task: { id: string; title: string; status: string } | null;
  artifacts: Artifact[];
}

export default function EscalationPage() {
  const org = useOrg();
  const { id } = useParams<{ id: string }>();
  const agents = useAgents();
  const [choice, setChoice] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const { data, error, isPending } = useOrgQuery<EscalationDetail>(["escalation", id], `/escalations/${id}`);
  const resolve = useOrgMutation<void>(() => ({
    path: `/escalations/${id}/resolve`,
    json: { option: choice, note },
  }));

  if (isPending) return <PageSkeleton />;
  if (error) return <ErrorState error={error} />;
  const { escalation } = data;
  const selected = escalation.options.find((option) => option.key === choice);
  const agent = escalation.agent_id ? agents.byId.get(escalation.agent_id) : undefined;
  const decided = escalation.options.find((option) => option.key === escalation.resolution_option);

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <div>
        <Link href={org.href("/inbox")} className="text-[13px] text-muted hover:text-ink">
          CEO Inbox
        </Link>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <h1 className="text-[22px] font-semibold tracking-tight">Decision required</h1>
          <StatusBadge status={escalation.status === "OPEN" ? "PENDING" : escalation.status === "RESOLVED" ? "COMPLETED" : "CANCELLED"} />
        </div>
        <p className="mt-1 text-sm text-muted">
          {humanize(escalation.kind)} · raised by {agent?.name ?? "the platform"} · {dateTime(escalation.created_at)}
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

      <Card className="space-y-4 p-5">
        <div>
          <h2 className="text-xs font-semibold tracking-wide text-muted uppercase">Question</h2>
          <p className="mt-1 text-[15px] font-medium text-ink">{escalation.question}</p>
        </div>
        {escalation.context && (
          <div>
            <h2 className="text-xs font-semibold tracking-wide text-muted uppercase">Context</h2>
            <p className="mt-1 text-[13.5px] whitespace-pre-line text-ink-soft">{escalation.context}</p>
          </div>
        )}
        {data.task && (
          <p className="text-[13px] text-muted">
            Task:{" "}
            <Link href={org.href(`/objectives/${data.objective?.id}?task=${data.task.id}`)} className="text-ink hover:underline">
              {data.task.title}
            </Link>{" "}
            — only this task is paused; the rest of the work continues.
          </p>
        )}
      </Card>

      {escalation.status === "OPEN" ? (
        <Card>
          <CardHeader title="Your decision" description="Pick one option. The workflow resumes as soon as you confirm." />
          <div className="space-y-2 border-t border-border px-5 py-4">
            {escalation.options.map((option) => (
              <button
                key={option.key}
                type="button"
                onClick={() => setChoice(option.key)}
                aria-pressed={choice === option.key}
                className={cn(
                  "block w-full rounded-lg border px-4 py-3 text-left transition-colors",
                  choice === option.key ? "border-accent bg-accent-soft" : "border-border hover:bg-surface-hover",
                )}
              >
                <span className="block text-sm font-medium text-ink">{option.label}</span>
                {option.description && <span className="mt-0.5 block text-[13px] text-muted">{option.description}</span>}
              </button>
            ))}
            {org.canDecide ? (
              <div className="space-y-3 pt-2">
                <Textarea
                  aria-label="Note for the team"
                  rows={3}
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  placeholder={selected?.requires_note ? "Required: your guidance or answer" : "Optional note for the team"}
                />
                <FormError message={resolve.error?.message} />
                <Button
                  variant="primary"
                  loading={resolve.isPending}
                  disabled={!choice || (selected?.requires_note && !note.trim())}
                  onClick={() => resolve.mutate()}
                >
                  Confirm decision
                </Button>
              </div>
            ) : (
              <p className="text-[13px] text-muted">Only owners and admins can decide.</p>
            )}
          </div>
        </Card>
      ) : (
        <Card className="p-5 text-[13.5px]">
          <p>
            <span className="font-medium">{escalation.status === "RESOLVED" ? `Decided: ${decided?.label ?? escalation.resolution_option}` : "Cancelled"}</span>
            {escalation.resolved_at && ` · ${dateTime(escalation.resolved_at)}`}
          </p>
          {escalation.resolution_note && <p className="mt-1 text-ink-soft">“{escalation.resolution_note}”</p>}
        </Card>
      )}

      {data.artifacts.length > 0 && (
        <Card>
          <CardHeader title="Work so far" description="Read the current deliverable before deciding." />
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
