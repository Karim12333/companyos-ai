"use client";

import { useState } from "react";

import { StatusBadge } from "@/components/ui/badge";
import { Card, CardHeader, PageHeader, Stat } from "@/components/ui/card";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/ui/feedback";
import { Select } from "@/components/ui/form";
import { compact, usd } from "@/lib/format";
import { useOrgQuery } from "@/lib/session";

interface Analytics {
  days: number;
  totals: { input_tokens: number; output_tokens: number; cost_usd: number; llm_calls: number };
  by_day: { date: string; tokens: number; cost_usd: number }[];
  by_agent: { agent: string; tokens: number; cost_usd: number; calls: number }[];
  by_model: { model: string; input_tokens: number; output_tokens: number; cost_usd: number }[];
  tasks: Record<string, number>;
  objectives: Record<string, number>;
  task_success_rate: number | null;
}

function DailyTokens({ data }: { data: Analytics["by_day"] }) {
  const [hover, setHover] = useState<number | null>(null);
  if (!data.length) return <EmptyState title="No AI usage in this period" />;
  const max = Math.max(...data.map((day) => day.tokens), 1);
  const active = hover !== null ? data[hover] : null;
  return (
    <div className="px-5 pb-5">
      <div className="mb-2 h-5 text-[13px] text-ink-soft tabular-nums">
        {active ? `${active.date} · ${compact(active.tokens)} tokens · ${usd(active.cost_usd)}` : `Peak ${compact(max)} tokens/day`}
      </div>
      <div className="relative flex h-44 items-end gap-[2px] border-b border-border" role="img" aria-label="Tokens per day">
        {data.map((day, index) => (
          <div
            key={day.date}
            className="flex h-full flex-1 cursor-default items-end"
            onMouseEnter={() => setHover(index)}
            onMouseLeave={() => setHover(null)}
          >
            <div
              className="w-full rounded-t-[4px] bg-accent transition-opacity"
              style={{ height: `${Math.max(2, (day.tokens / max) * 100)}%`, opacity: hover === null || hover === index ? 1 : 0.45 }}
            />
          </div>
        ))}
      </div>
      <div className="mt-1.5 flex justify-between text-[11px] text-faint">
        <span>{data[0].date}</span>
        <span>{data[data.length - 1].date}</span>
      </div>
    </div>
  );
}

export default function AnalyticsPage() {
  const [days, setDays] = useState(30);
  const { data, error, isPending } = useOrgQuery<Analytics>(["analytics", days], `/analytics?days=${days}`);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Analytics"
        description="AI usage, cost and execution outcomes. Costs are estimates from token counts and model pricing."
        actions={
          <Select aria-label="Time range" value={days} onChange={(event) => setDays(Number(event.target.value))} className="w-36">
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </Select>
        }
      />
      {isPending ? (
        <PageSkeleton />
      ) : error ? (
        <ErrorState error={error} />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <Stat label="Estimated AI cost" value={usd(data.totals.cost_usd)} />
            <Stat label="Tokens" value={compact(data.totals.input_tokens + data.totals.output_tokens)} hint={`${compact(data.totals.input_tokens)} in · ${compact(data.totals.output_tokens)} out`} />
            <Stat label="Model calls" value={compact(data.totals.llm_calls)} />
            <Stat label="Task success rate" value={data.task_success_rate === null ? "—" : `${Math.round(data.task_success_rate * 100)}%`} />
          </div>
          <Card>
            <CardHeader title="Tokens per day" />
            <DailyTokens data={data.by_day} />
          </Card>
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader title="Usage by agent" />
              {data.by_agent.length === 0 ? (
                <EmptyState title="No agent usage yet" />
              ) : (
                <table className="w-full text-[13px]">
                  <thead className="border-y border-border bg-surface-muted text-left text-xs text-muted">
                    <tr>
                      <th className="px-5 py-2 font-medium">Agent</th>
                      <th className="px-3 py-2 font-medium">Share of tokens</th>
                      <th className="px-5 py-2 text-right font-medium">Cost</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {data.by_agent.map((row) => {
                      const max = Math.max(...data.by_agent.map((item) => item.tokens), 1);
                      return (
                        <tr key={row.agent}>
                          <td className="px-5 py-2.5">{row.agent}</td>
                          <td className="w-1/2 px-3">
                            <div className="flex items-center gap-2" title={`${row.tokens} tokens · ${row.calls} calls`}>
                              <div className="h-2 rounded-r-[4px] bg-accent" style={{ width: `${Math.max(2, (row.tokens / max) * 100)}%` }} />
                              <span className="text-xs text-muted tabular-nums">{compact(row.tokens)}</span>
                            </div>
                          </td>
                          <td className="px-5 text-right tabular-nums">{usd(row.cost_usd)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </Card>
            <div className="space-y-6">
              <Card>
                <CardHeader title="Usage by model" />
                <table className="w-full text-[13px]">
                  <tbody className="divide-y divide-border border-t border-border">
                    {data.by_model.map((row) => (
                      <tr key={row.model}>
                        <td className="px-5 py-2.5 font-mono text-[12px]">{row.model}</td>
                        <td className="px-3 text-muted tabular-nums">{compact(row.input_tokens + row.output_tokens)} tokens</td>
                        <td className="px-5 text-right tabular-nums">{usd(row.cost_usd)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
              <Card>
                <CardHeader title="Execution outcomes" />
                <div className="flex flex-wrap gap-2 border-t border-border px-5 py-4">
                  {Object.entries(data.tasks).map(([status, count]) => (
                    <span key={status} className="flex items-center gap-1.5 text-[13px]">
                      <StatusBadge status={status} /> <span className="tabular-nums">{count}</span>
                    </span>
                  ))}
                  {Object.keys(data.tasks).length === 0 && <span className="text-[13px] text-muted">No tasks in this period</span>}
                </div>
              </Card>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
