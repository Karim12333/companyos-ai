"use client";

import { AlertOctagon, CheckCircle2, CircleHelp, Eye, Info, ShieldAlert, type LucideIcon } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, PageHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/ui/feedback";
import { Tabs } from "@/components/ui/tabs";
import { cn, timeAgo } from "@/lib/format";
import { useAgents, useOrgMutation } from "@/lib/hooks";
import { useOrg, useOrgQuery } from "@/lib/session";
import type { InboxItem } from "@/lib/types";

type Category = "ALL" | InboxItem["category"];

const CATEGORY: Record<InboxItem["category"], { label: string; icon: LucideIcon; tone: Tone; action: string }> = {
  APPROVAL_REQUIRED: { label: "Approval required", icon: ShieldAlert, tone: "warning", action: "Review" },
  DECISION_REQUIRED: { label: "Decision required", icon: CircleHelp, tone: "accent", action: "Open" },
  REVIEW_RECOMMENDED: { label: "Review recommended", icon: Eye, tone: "info", action: "Open" },
  COMPLETED: { label: "Completed", icon: CheckCircle2, tone: "success", action: "View" },
  FAILED: { label: "Failed", icon: AlertOctagon, tone: "danger", action: "View issue" },
  INFO: { label: "Info", icon: Info, tone: "neutral", action: "Open" },
};

const ICON_COLOR: Record<Tone, string> = {
  neutral: "text-muted",
  accent: "text-accent",
  success: "text-success",
  warning: "text-warning",
  danger: "text-danger",
  info: "text-info",
};

interface InboxResponse {
  items: InboxItem[];
  unread_by_category: Partial<Record<InboxItem["category"], number>>;
  unread_total: number;
  action_required: number;
}

export default function InboxPage() {
  const org = useOrg();
  const agents = useAgents();
  const [category, setCategory] = useState<Category>("ALL");
  const query = category === "ALL" ? "" : `?category=${category}`;
  const { data, error, isPending } = useOrgQuery<InboxResponse>(["inbox", category], `/inbox${query}`);
  const markRead = useOrgMutation<string>((id) => ({ path: `/inbox/${id}/read` }));
  const markAll = useOrgMutation<void>(() => ({ path: "/inbox/read-all" }));

  const unread = data?.unread_by_category ?? {};
  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader
        title="CEO Inbox"
        description="Everything that needs your attention, in one place."
        actions={
          <Button size="sm" onClick={() => markAll.mutate()} loading={markAll.isPending}>
            Mark all as read
          </Button>
        }
      />
      <Tabs<Category>
        value={category}
        onChange={setCategory}
        tabs={[
          { value: "ALL", label: "All", count: data?.unread_total },
          { value: "APPROVAL_REQUIRED", label: "Approvals", count: unread.APPROVAL_REQUIRED },
          { value: "FAILED", label: "Failures", count: unread.FAILED },
          { value: "COMPLETED", label: "Completed", count: unread.COMPLETED },
        ]}
      />
      <div className="mt-4">
        {isPending ? (
          <PageSkeleton />
        ) : error ? (
          <ErrorState error={error} />
        ) : data.items.length === 0 ? (
          <Card>
            <EmptyState title="Inbox zero" description="Approvals, completed objectives and failures will appear here." />
          </Card>
        ) : (
          <Card>
            <ul className="divide-y divide-border">
              {data.items.map((item) => {
                const meta = CATEGORY[item.category];
                const agent = item.agent_id ? agents.byId.get(item.agent_id) : undefined;
                return (
                  <li key={item.id} className={cn("flex gap-3 px-5 py-4", !item.is_read && "bg-accent-soft/40")}>
                    <meta.icon className={cn("mt-0.5 size-4 shrink-0", ICON_COLOR[meta.tone])} aria-hidden />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone={meta.tone}>{meta.label}</Badge>
                        {item.action_required && <Badge tone="warning">Action required</Badge>}
                        {!item.is_read && <span className="size-1.5 rounded-full bg-accent" aria-label="Unread" />}
                      </div>
                      <p className="mt-1.5 text-sm font-medium text-ink">{item.title}</p>
                      {item.summary && <p className="mt-0.5 line-clamp-2 text-[13px] text-muted">{item.summary}</p>}
                      <p className="mt-1 text-xs text-faint">
                        {agent ? `${agent.name} · ` : ""}
                        {timeAgo(item.created_at)}
                      </p>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-2">
                      <Link
                        href={item.link ? org.href(item.link) : org.href("/inbox")}
                        onClick={() => !item.is_read && markRead.mutate(item.id)}
                        className="rounded-lg border border-border px-3 py-1.5 text-[13px] font-medium hover:bg-surface-hover"
                      >
                        {meta.action}
                      </Link>
                    </div>
                  </li>
                );
              })}
            </ul>
          </Card>
        )}
      </div>
    </div>
  );
}
