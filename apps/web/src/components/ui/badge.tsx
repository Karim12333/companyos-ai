import type { ReactNode } from "react";

import { cn, humanize } from "@/lib/format";

export type Tone = "neutral" | "accent" | "success" | "warning" | "danger" | "info";

const tones: Record<Tone, string> = {
  neutral: "bg-surface-muted text-ink-soft",
  accent: "bg-accent-soft text-accent-ink",
  success: "bg-success-soft text-success",
  warning: "bg-warning-soft text-warning",
  danger: "bg-danger-soft text-danger",
  info: "bg-info-soft text-info",
};

export function Badge({
  tone = "neutral",
  children,
  className,
  dot,
}: {
  tone?: Tone;
  children: ReactNode;
  className?: string;
  dot?: boolean;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        tones[tone],
        className,
      )}
    >
      {dot && <span className="live-dot size-1.5 rounded-full bg-current" aria-hidden />}
      {children}
    </span>
  );
}

const STATUS_TONES: Record<string, Tone> = {
  DRAFT: "neutral",
  PLANNING: "info",
  RUNNING: "info",
  READY: "neutral",
  QUEUED: "neutral",
  WAITING: "neutral",
  REVIEW: "accent",
  REVIEWING: "accent",
  WAITING_FOR_APPROVAL: "warning",
  PAUSED: "neutral",
  COMPLETED: "success",
  COMPLETED_WITH_ISSUES: "warning",
  FAILED: "danger",
  BLOCKED: "danger",
  CANCELLED: "neutral",
  PENDING: "warning",
  APPROVED: "success",
  REJECTED: "danger",
  EXPIRED: "neutral",
  working: "info",
  idle: "neutral",
  paused: "neutral",
  active: "info",
  completed_today: "success",
  accepted: "success",
  changes_requested: "warning",
  pending: "warning",
  not_required: "neutral",
  connected: "success",
  not_configured: "neutral",
  error: "danger",
  disabled: "neutral",
};

const LIVE = new Set(["RUNNING", "PLANNING", "REVIEWING", "REVIEW", "working", "active"]);

const LABELS: Record<string, string> = {
  WAITING_FOR_APPROVAL: "Awaiting approval",
  COMPLETED_WITH_ISSUES: "Completed with issues",
  completed_today: "Completed today",
  not_required: "No review",
  REVIEW: "In review",
};

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  return (
    <Badge tone={STATUS_TONES[status] ?? "neutral"} dot={LIVE.has(status)} className={className}>
      {LABELS[status] ?? humanize(status)}
    </Badge>
  );
}

const RISK: Record<string, [Tone, string]> = {
  "1": ["neutral", "Level 1 · Autonomous"],
  "2": ["info", "Level 2 · Controlled"],
  "3": ["warning", "Level 3 · Human approval"],
};

export function RiskBadge({ level }: { level: string }) {
  const [tone, label] = RISK[level] ?? RISK["3"];
  return <Badge tone={tone}>{label}</Badge>;
}
