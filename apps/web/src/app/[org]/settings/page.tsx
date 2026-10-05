"use client";

import { useState, type FormEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, PageHeader } from "@/components/ui/card";
import { ErrorState, PageSkeleton } from "@/components/ui/feedback";
import { Field, FormError, Input, Select } from "@/components/ui/form";
import { Tabs } from "@/components/ui/tabs";
import { dateTime, humanize } from "@/lib/format";
import { useOrgMutation } from "@/lib/hooks";
import { useOrg, useOrgQuery } from "@/lib/session";
import type { OrgSettings } from "@/lib/types";

type Tab = "general" | "policies" | "members" | "audit";

export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>("general");
  return (
    <div className="mx-auto max-w-4xl">
      <PageHeader title="Settings" description="Limits, budgets, approval policies, members and the audit trail." />
      <Tabs<Tab>
        value={tab}
        onChange={setTab}
        tabs={[
          { value: "general", label: "Limits & notifications" },
          { value: "policies", label: "Approval policies" },
          { value: "members", label: "Members" },
          { value: "audit", label: "Audit log" },
        ]}
      />
      <div className="mt-5">
        {tab === "general" && <GeneralSettings />}
        {tab === "policies" && <Policies />}
        {tab === "members" && <Members />}
        {tab === "audit" && <Audit />}
      </div>
    </div>
  );
}

function GeneralSettings() {
  const org = useOrg();
  const [saved, setSaved] = useState(false);
  const { data, error, isPending } = useOrgQuery<OrgSettings>(["settings"], "/settings");
  const update = useOrgMutation<Record<string, unknown>>((json) => ({ path: "/settings", method: "PATCH", json }), {
    onSuccess: () => setSaved(true),
  });
  if (isPending) return <PageSkeleton />;
  if (error) return <ErrorState error={error} />;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setSaved(false);
    update.mutate({
      ceo_name: form.get("ceo_name") || null,
      notification_emails: String(form.get("notification_emails")).split(",").map((item) => item.trim()).filter(Boolean),
      max_parallel_tasks: Number(form.get("max_parallel_tasks")),
      max_task_iterations: Number(form.get("max_task_iterations")),
      max_review_revisions: Number(form.get("max_review_revisions")),
      max_messages_per_task: Number(form.get("max_messages_per_task")),
      objective_budget_usd: Number(form.get("objective_budget_usd")),
      daily_budget_usd: Number(form.get("daily_budget_usd")),
    });
  }
  const disabled = !org.canManage;
  return (
    <Card className="p-5 sm:p-6">
      <form onSubmit={submit} className="space-y-6">
        <section className="grid gap-4 sm:grid-cols-2">
          <Field label="How agents address you" htmlFor="ceo_name">
            <Input id="ceo_name" name="ceo_name" defaultValue={data.ceo_name ?? ""} disabled={disabled} />
          </Field>
          <Field label="Notification emails" htmlFor="notification_emails" hint="Comma-separated. Internal notifications only.">
            <Input id="notification_emails" name="notification_emails" defaultValue={data.notification_emails.join(", ")} disabled={disabled} />
          </Field>
        </section>
        <section>
          <h2 className="mb-3 text-sm font-semibold">Execution limits</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Parallel tasks per objective" htmlFor="max_parallel_tasks">
              <Input id="max_parallel_tasks" name="max_parallel_tasks" type="number" min={1} max={16} defaultValue={data.max_parallel_tasks} disabled={disabled} />
            </Field>
            <Field label="Max reasoning iterations per task" htmlFor="max_task_iterations">
              <Input id="max_task_iterations" name="max_task_iterations" type="number" min={1} max={20} defaultValue={data.max_task_iterations} disabled={disabled} />
            </Field>
            <Field label="Max review revisions" htmlFor="max_review_revisions">
              <Input id="max_review_revisions" name="max_review_revisions" type="number" min={0} max={5} defaultValue={data.max_review_revisions} disabled={disabled} />
            </Field>
            <Field label="Max agent messages per task" htmlFor="max_messages_per_task">
              <Input id="max_messages_per_task" name="max_messages_per_task" type="number" min={0} max={20} defaultValue={data.max_messages_per_task} disabled={disabled} />
            </Field>
          </div>
        </section>
        <section>
          <h2 className="mb-3 text-sm font-semibold">Budgets (USD)</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Default budget per objective" htmlFor="objective_budget_usd" hint="Agents stop when an objective reaches it.">
              <Input id="objective_budget_usd" name="objective_budget_usd" type="number" min={0} step="0.5" defaultValue={Number(data.objective_budget_usd)} disabled={disabled} />
            </Field>
            <Field label="Daily AI budget" htmlFor="daily_budget_usd">
              <Input id="daily_budget_usd" name="daily_budget_usd" type="number" min={0} step="1" defaultValue={Number(data.daily_budget_usd)} disabled={disabled} />
            </Field>
          </div>
        </section>
        <FormError message={update.error?.message} />
        {!disabled && (
          <div className="flex items-center gap-3">
            <Button type="submit" variant="primary" loading={update.isPending}>
              Save settings
            </Button>
            {saved && <span className="text-[13px] text-success">Saved</span>}
          </div>
        )}
      </form>
    </Card>
  );
}

function Policies() {
  const org = useOrg();
  const { data, error, isPending } = useOrgQuery<{ id: string; action_key: string; requires_approval: boolean; description: string }[]>(
    ["approval-policies"],
    "/approval-policies",
  );
  const update = useOrgMutation<{ id: string; requires_approval: boolean }>(({ id, requires_approval }) => ({
    path: `/approval-policies/${id}`,
    method: "PUT",
    json: { requires_approval },
  }));
  if (isPending) return <PageSkeleton />;
  if (error) return <ErrorState error={error} />;
  return (
    <div className="space-y-4">
      <Card className="p-5 text-[13.5px] text-ink-soft">
        <p>
          <span className="font-medium text-ink">Level 1 — autonomous:</span> reading, research, drafting, internal artifacts. Always allowed.
        </p>
        <p className="mt-1">
          <span className="font-medium text-ink">Level 2 — controlled:</span> configurable below per action.
        </p>
        <p className="mt-1">
          <span className="font-medium text-ink">Level 3 — human approval:</span> publishing, external email, spending, production changes.
          Always requires your approval and cannot be turned off.
        </p>
      </Card>
      <Card>
        <CardHeader title="Level 2 actions" />
        <ul className="divide-y divide-border border-t border-border">
          {data.map((policy) => (
            <li key={policy.id} className="flex items-center justify-between gap-4 px-5 py-3">
              <div>
                <p className="font-mono text-[13px]">{policy.action_key}</p>
                <p className="text-xs text-muted">{policy.description}</p>
              </div>
              <Select
                aria-label={`Policy for ${policy.action_key}`}
                className="w-48"
                value={policy.requires_approval ? "approval" : "auto"}
                disabled={!org.canManage}
                onChange={(event) => update.mutate({ id: policy.id, requires_approval: event.target.value === "approval" })}
              >
                <option value="approval">Requires approval</option>
                <option value="auto">Allowed automatically</option>
              </Select>
            </li>
          ))}
        </ul>
      </Card>
    </div>
  );
}

function Members() {
  const org = useOrg();
  const { data, error, isPending } = useOrgQuery<{ id: string; email: string; full_name: string; role: string; created_at: string }[]>(
    ["members"],
    "/members",
  );
  const add = useOrgMutation<Record<string, unknown>>((json) => ({ path: "/members", json }));
  if (isPending) return <PageSkeleton />;
  if (error) return <ErrorState error={error} />;
  return (
    <Card>
      <ul className="divide-y divide-border">
        {data.map((member) => (
          <li key={member.id} className="flex items-center justify-between px-5 py-3">
            <div>
              <p className="text-sm font-medium">{member.full_name}</p>
              <p className="text-xs text-muted">{member.email}</p>
            </div>
            <Badge>{humanize(member.role)}</Badge>
          </li>
        ))}
      </ul>
      {org.canManage && (
        <form
          className="flex flex-col gap-2 border-t border-border px-5 py-4 sm:flex-row"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            add.mutate({ email: form.get("email"), role: form.get("role") });
            event.currentTarget.reset();
          }}
        >
          <Input name="email" type="email" required placeholder="colleague@company.com" aria-label="Member email" />
          <Select name="role" defaultValue="member" aria-label="Role" className="sm:w-36">
            <option value="admin">Admin</option>
            <option value="member">Member</option>
            <option value="viewer">Viewer</option>
          </Select>
          <Button type="submit" loading={add.isPending}>
            Add member
          </Button>
        </form>
      )}
      <div className="px-5 pb-4">
        <FormError message={add.error?.message} />
      </div>
    </Card>
  );
}

function Audit() {
  const org = useOrg();
  const { data, error, isPending } = useOrgQuery<
    { id: string; action: string; actor_type: string; outcome: string; target_type: string | null; details: Record<string, unknown>; created_at: string }[]
  >(["audit"], "/audit", { enabled: org.canManage });
  if (!org.canManage) return <Card className="p-5 text-sm text-muted">Only owners and admins can view the audit log.</Card>;
  if (isPending) return <PageSkeleton />;
  if (error) return <ErrorState error={error} />;
  const tone = (outcome: string) => (outcome === "success" ? "success" : outcome === "denied" || outcome === "failure" ? "danger" : "warning");
  return (
    <Card className="overflow-x-auto">
      <table className="w-full text-[13px]">
        <thead className="border-b border-border bg-surface-muted text-left text-xs text-muted">
          <tr>
            <th className="px-5 py-2.5 font-medium">When</th>
            <th className="px-3 py-2.5 font-medium">Action</th>
            <th className="px-3 py-2.5 font-medium">Actor</th>
            <th className="px-5 py-2.5 text-right font-medium">Outcome</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {data.map((row) => (
            <tr key={row.id}>
              <td className="px-5 py-2 whitespace-nowrap text-muted">{dateTime(row.created_at)}</td>
              <td className="px-3 font-mono text-[12px]">{row.action}</td>
              <td className="px-3 text-muted">{row.actor_type}</td>
              <td className="px-5 text-right">
                <Badge tone={tone(row.outcome)}>{humanize(row.outcome)}</Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}
