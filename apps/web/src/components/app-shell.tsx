"use client";

import {
  Activity,
  BarChart3,
  BookOpen,
  ChevronsUpDown,
  FileText,
  FolderKanban,
  Inbox,
  LayoutDashboard,
  LogOut,
  Menu,
  Network,
  Plug,
  Plus,
  Settings,
  ShieldCheck,
  Target,
  Users,
  X,
} from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { Logo } from "@/components/logo";
import { LinkButton } from "@/components/ui/button";
import { PageSkeleton } from "@/components/ui/feedback";
import { ApiError } from "@/lib/api";
import { cn, initials } from "@/lib/format";
import { OrgProvider, useAuthActions, useLiveEvents, useMe, useOrg, useOrgQuery, type LiveStatus } from "@/lib/session";
import type { AIStatus, Me } from "@/lib/types";

const NAV = [
  { href: "/headquarters", label: "Headquarters", icon: LayoutDashboard },
  { href: "/inbox", label: "CEO Inbox", icon: Inbox, badge: true },
  { href: "/objectives", label: "Objectives", icon: Target },
  { href: "/projects", label: "Projects", icon: FolderKanban },
  { href: "/departments", label: "Departments", icon: Network },
  { href: "/agents", label: "Agents", icon: Users },
  { href: "/artifacts", label: "Artifacts", icon: FileText },
  { href: "/knowledge", label: "Knowledge", icon: BookOpen },
  { href: "/activity", label: "Activity", icon: Activity },
  { href: "/integrations", label: "Integrations", icon: Plug },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function OrgShell({ children }: { children: ReactNode }) {
  const { org: slug } = useParams<{ org: string }>();
  const router = useRouter();
  const pathname = usePathname();
  const { data: me, error, isPending } = useMe();

  useEffect(() => {
    if (error instanceof ApiError && error.status === 401) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [error, pathname, router]);

  if (isPending || !me) {
    return (
      <div className="mx-auto max-w-6xl p-8">
        <PageSkeleton />
      </div>
    );
  }
  const organization = me.organizations.find((item) => item.slug === slug);
  if (!organization) {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-6 text-center">
        <p className="text-sm text-muted">This organization does not exist or you are not a member.</p>
        <LinkButton href="/">Go to my organization</LinkButton>
      </main>
    );
  }
  return (
    <OrgProvider organization={organization}>
      <Shell me={me}>{children}</Shell>
    </OrgProvider>
  );
}

function Shell({ me, children }: { me: Me; children: ReactNode }) {
  const org = useOrg();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const live = useLiveEvents(org.id);
  const { data: inbox } = useOrgQuery<{ action_required: number; unread_total: number }>(
    ["inbox", "summary"],
    "/inbox?limit=1",
    { refetchInterval: 30_000 },
  );
  const { data: organization } = useOrgQuery<{ ai: AIStatus }>(["organization"], "");

  const nav = (
    <nav aria-label="Main" className="flex flex-col gap-0.5">
      {NAV.map((item) => {
        const href = org.href(item.href);
        const active = pathname === href || pathname.startsWith(`${href}/`);
        const count = item.badge ? (inbox?.action_required ?? 0) : 0;
        return (
          <Link
            key={item.href}
            href={href}
            aria-current={active ? "page" : undefined}
            onClick={() => setOpen(false)}
            className={cn(
              "flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13.5px] transition-colors",
              active ? "bg-surface-hover font-medium text-ink" : "text-ink-soft hover:bg-surface-hover hover:text-ink",
            )}
          >
            <item.icon className="size-4 shrink-0 opacity-80" aria-hidden />
            <span className="flex-1">{item.label}</span>
            {count > 0 && (
              <span className="rounded-md bg-warning-soft px-1.5 text-[11px] font-semibold text-warning tabular-nums">
                {count}
              </span>
            )}
          </Link>
        );
      })}
      {me.user.is_platform_admin && (
        <Link
          href={org.href("/admin")}
          onClick={() => setOpen(false)}
          className={cn(
            "mt-3 flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-[13.5px] transition-colors",
            pathname.endsWith("/admin") ? "bg-surface-hover font-medium text-ink" : "text-ink-soft hover:bg-surface-hover",
          )}
        >
          <ShieldCheck className="size-4 opacity-80" aria-hidden />
          Platform Admin
        </Link>
      )}
    </nav>
  );

  const sidebar = (
    <div className="flex h-full flex-col gap-5 px-3 py-4">
      <div className="flex items-center justify-between px-1.5">
        <Logo />
        <LiveIndicator status={live} />
      </div>
      <OrgSwitcher me={me} />
      <div className="flex-1 overflow-y-auto">{nav}</div>
      <UserMenu me={me} />
    </div>
  );

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[248px_1fr]">
      <aside className="sticky top-0 hidden h-screen border-r border-border bg-surface lg:block">{sidebar}</aside>
      <header className="sticky top-0 z-30 flex items-center justify-between border-b border-border bg-surface/95 px-4 py-2.5 backdrop-blur lg:hidden">
        <button type="button" onClick={() => setOpen(true)} aria-label="Open navigation" className="rounded-md p-1.5 hover:bg-surface-hover">
          <Menu className="size-5" />
        </button>
        <Logo />
        <Link href={org.href("/inbox")} aria-label="CEO Inbox" className="relative rounded-md p-1.5 hover:bg-surface-hover">
          <Inbox className="size-5" />
          {(inbox?.action_required ?? 0) > 0 && <span className="absolute top-1 right-1 size-2 rounded-full bg-warning" />}
        </Link>
      </header>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-black/30" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 left-0 w-72 bg-surface shadow-xl">
            <button type="button" onClick={() => setOpen(false)} aria-label="Close navigation" className="absolute top-4 right-3 rounded-md p-1 hover:bg-surface-hover">
              <X className="size-4" />
            </button>
            {sidebar}
          </div>
        </div>
      )}
      <main className="min-w-0">
        {organization && !organization.ai.configured && (
          <div className="border-b border-warning/20 bg-warning-soft px-4 py-2 text-center text-[13px] text-warning sm:px-8">
            Agents are running on the offline mock model.{" "}
            {org.canManage ? (
              <Link href={org.href("/integrations")} className="font-medium underline underline-offset-2">
                Add your AI provider key
              </Link>
            ) : (
              "Ask an admin to configure an AI provider"
            )}{" "}
            for real output.
          </div>
        )}
        <div className="mx-auto max-w-7xl px-4 py-6 sm:px-8 sm:py-8">{children}</div>
      </main>
    </div>
  );
}

function LiveIndicator({ status }: { status: LiveStatus }) {
  const label = { live: "Live", connecting: "Connecting", offline: "Reconnecting" }[status];
  return (
    <span className="flex items-center gap-1.5 text-[11px] text-muted" title={`Realtime updates: ${label}`}>
      <span className={cn("size-1.5 rounded-full", status === "live" ? "live-dot bg-success" : "bg-faint")} />
      {label}
    </span>
  );
}

function OrgSwitcher({ me }: { me: Me }) {
  const org = useOrg();
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 rounded-lg border border-border px-2.5 py-2 text-left hover:bg-surface-hover"
      >
        <span className="flex size-6 items-center justify-center rounded-md bg-accent-soft text-[11px] font-semibold text-accent-ink">
          {initials(org.name)}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-medium">{org.name}</span>
          <span className="block text-[11px] text-muted capitalize">{org.role}</span>
        </span>
        <ChevronsUpDown className="size-3.5 text-muted" />
      </button>
      {open && (
        <div className="absolute inset-x-0 top-full z-20 mt-1 rounded-lg border border-border bg-surface p-1 shadow-lg">
          {me.organizations.map((item) => (
            <Link
              key={item.id}
              href={`/${item.slug}/headquarters`}
              onClick={() => setOpen(false)}
              className={cn("block truncate rounded-md px-2.5 py-1.5 text-[13px] hover:bg-surface-hover", item.id === org.id && "font-medium")}
            >
              {item.name}
            </Link>
          ))}
          <Link href="/new-organization" className="mt-1 flex items-center gap-1.5 rounded-md border-t border-border px-2.5 py-1.5 text-[13px] text-muted hover:bg-surface-hover">
            <Plus className="size-3.5" /> New organization
          </Link>
        </div>
      )}
    </div>
  );
}

function UserMenu({ me }: { me: Me }) {
  const router = useRouter();
  const { logout } = useAuthActions();
  return (
    <div className="flex items-center gap-2.5 border-t border-border px-1.5 pt-3">
      <span className="flex size-7 items-center justify-center rounded-full bg-surface-muted text-[11px] font-semibold">{initials(me.user.full_name)}</span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-[13px] font-medium">{me.user.full_name}</p>
        <p className="truncate text-[11px] text-muted">{me.user.email}</p>
      </div>
      <button
        type="button"
        aria-label="Sign out"
        className="rounded-md p-1.5 text-muted hover:bg-surface-hover hover:text-ink"
        onClick={async () => {
          await logout();
          router.replace("/login");
        }}
      >
        <LogOut className="size-4" />
      </button>
    </div>
  );
}
