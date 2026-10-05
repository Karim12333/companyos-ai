import { AlertTriangle, CheckCircle2 } from "lucide-react";
import Link from "next/link";

import { StatusBadge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { duration, usd } from "@/lib/format";
import type { ExecutiveSummary } from "@/lib/types";

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <dt className="text-xs text-muted">{label}</dt>
      <dd className="mt-0.5 text-lg font-semibold tabular-nums">{value}</dd>
    </div>
  );
}

function List({ title, items, tone }: { title: string; items: string[]; tone?: "danger" }) {
  if (!items.length) return null;
  return (
    <section>
      <h3 className="mb-2 text-sm font-semibold">{title}</h3>
      <ul className="space-y-1.5 text-[13.5px] text-ink-soft">
        {items.map((item) => (
          <li key={item} className="flex gap-2">
            <span className={`mt-2 size-1 shrink-0 rounded-full ${tone === "danger" ? "bg-danger" : "bg-faint"}`} />
            {item}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function ExecutiveReport({ summary, reportHref }: { summary: ExecutiveSummary; reportHref?: string }) {
  const narrative = summary.narrative;
  return (
    <Card className="overflow-hidden">
      <div className="border-b border-border px-6 py-5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-semibold tracking-wide text-muted uppercase">Executive report</span>
          <StatusBadge status={summary.status} />
        </div>
        <h2 className="mt-2 text-lg font-semibold tracking-tight">{narrative.headline}</h2>
        <p className="mt-2 max-w-3xl text-[14px] leading-relaxed text-ink-soft">{narrative.overall_assessment}</p>
      </div>
      <dl className="grid grid-cols-2 gap-5 border-b border-border px-6 py-5 sm:grid-cols-3 lg:grid-cols-6">
        <Metric label="Duration" value={duration(summary.duration_seconds)} />
        <Metric label="Agents" value={summary.agents_involved} />
        <Metric label="Tasks completed" value={`${summary.tasks_completed}/${summary.tasks_total}`} />
        <Metric label="Artifacts" value={summary.artifacts_created} />
        <Metric label="Issues resolved" value={summary.issues_resolved} />
        <Metric label="AI cost" value={usd(summary.cost_usd)} />
      </dl>
      <div className="grid gap-6 px-6 py-5 lg:grid-cols-2">
        <div className="space-y-5">
          <section className="rounded-lg border border-accent/20 bg-accent-soft px-4 py-3">
            <h3 className="text-xs font-semibold tracking-wide text-accent-ink uppercase">Recommendation</h3>
            <p className="mt-1 text-[14px] font-medium text-ink">{narrative.recommendation}</p>
          </section>
          <List title="Completed" items={summary.completed_titles} />
          <List title="Key findings" items={narrative.key_findings} />
        </div>
        <div className="space-y-5">
          {summary.failures.length > 0 ? (
            <section>
              <h3 className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-danger">
                <AlertTriangle className="size-4" /> Failures
              </h3>
              <ul className="space-y-2">
                {summary.failures.map((failure) => (
                  <li key={failure.task} className="rounded-lg border border-danger/20 bg-danger-soft px-3 py-2 text-[13px]">
                    <p className="font-medium text-danger">{failure.task}</p>
                    <p className="text-ink-soft">{failure.message}</p>
                    {failure.recoverable && <p className="mt-1 text-xs text-muted">Recoverable — can be retried from the plan.</p>}
                  </li>
                ))}
              </ul>
            </section>
          ) : (
            <p className="flex items-center gap-2 text-sm text-success">
              <CheckCircle2 className="size-4" /> No failures
            </p>
          )}
          <section className="text-[13.5px] text-ink-soft">
            <h3 className="mb-1 text-sm font-semibold text-ink">Approvals</h3>
            {summary.approvals_total} requested · {summary.approvals_approved} approved · {summary.approvals_rejected} rejected ·{" "}
            {summary.approvals_pending} pending
          </section>
          <List title="Risks" items={narrative.risks} tone="danger" />
          <List title="Next actions" items={narrative.next_actions} />
          {reportHref && (
            <Link href={reportHref} className="inline-block text-[13px] font-medium text-accent hover:underline">
              Open full report document →
            </Link>
          )}
        </div>
      </div>
    </Card>
  );
}
