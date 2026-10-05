"use client";

import {
  AlertOctagon,
  CheckCircle2,
  CircleDot,
  FileText,
  GitBranch,
  MessageSquare,
  PlayCircle,
  ShieldAlert,
  ShieldCheck,
  ShieldX,
  Sparkles,
  type LucideIcon,
} from "lucide-react";

import { EmptyState } from "@/components/ui/feedback";
import { clock, cn, dateTime, timeAgo } from "@/lib/format";
import type { ActivityEvent } from "@/lib/types";

const ICONS: [string, LucideIcon, string][] = [
  ["task.failed", AlertOctagon, "text-danger"],
  ["objective.finished", Sparkles, "text-success"],
  ["task.completed", CheckCircle2, "text-success"],
  ["review.accepted", ShieldCheck, "text-success"],
  ["review.revision_requested", MessageSquare, "text-warning"],
  ["approval.requested", ShieldAlert, "text-warning"],
  ["approval.approved", ShieldCheck, "text-success"],
  ["approval.rejected", ShieldX, "text-danger"],
  ["artifact.", FileText, "text-accent"],
  ["task.delegated", GitBranch, "text-info"],
  ["message.", MessageSquare, "text-info"],
  ["task.started", PlayCircle, "text-info"],
  ["objective.planned", GitBranch, "text-accent"],
];

function isToday(value: string): boolean {
  return new Date(value).toDateString() === new Date().toDateString();
}

function iconFor(eventType: string): [LucideIcon, string] {
  const match = ICONS.find(([prefix]) => eventType.startsWith(prefix));
  return match ? [match[1], match[2]] : [CircleDot, "text-faint"];
}

export function ActivityFeed({
  events,
  compact,
  empty = "No activity yet",
}: {
  events: ActivityEvent[];
  compact?: boolean;
  empty?: string;
}) {
  if (!events.length) return <EmptyState title={empty} description="Events appear here as your organization works." />;
  return (
    <ol className="divide-y divide-border">
      {events.map((event) => {
        const [Icon, color] = iconFor(event.event_type);
        return (
          <li key={event.id} className={cn("flex items-start gap-3 px-5", compact ? "py-2.5" : "py-3")}>
            <Icon className={cn("mt-0.5 size-4 shrink-0", color)} aria-hidden />
            <p className="min-w-0 flex-1 text-[13.5px] leading-snug text-ink-soft">{event.summary}</p>
            <time
              dateTime={event.created_at}
              title={new Date(event.created_at).toLocaleString()}
              className="shrink-0 text-xs text-faint tabular-nums"
            >
              {compact ? timeAgo(event.created_at) : isToday(event.created_at) ? clock(event.created_at) : dateTime(event.created_at)}
            </time>
          </li>
        );
      })}
    </ol>
  );
}
