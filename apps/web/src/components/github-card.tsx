"use client";

import { Lock } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Badge, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Field, FormError, Input } from "@/components/ui/form";
import { dateTime } from "@/lib/format";
import { useOrgMutation } from "@/lib/hooks";
import { useOrg } from "@/lib/session";
import type { Integration } from "@/lib/types";

export function GitHubCard({ integration }: { integration?: Integration }) {
  const org = useOrg();
  const config = (integration?.config ?? {}) as unknown as { allowed_repos?: string[]; default_branch?: string; write_enabled?: boolean };
  const [message, setMessage] = useState<string | null>(null);
  const save = useOrgMutation<Record<string, unknown>, Integration>((json) => ({ path: "/integrations/github", method: "PUT", json }), {
    onSuccess: () => setMessage("Saved."),
  });
  const test = useOrgMutation<void, Integration>(() => ({ path: "/integrations/github/test" }), {
    onSuccess: (result) => setMessage(result.health_message),
  });
  const remove = useOrgMutation<void>(() => ({ path: "/integrations/github/secret", method: "DELETE" }));

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setMessage(null);
    save.mutate({
      token: String(form.get("token") ?? "").trim() || null,
      allowed_repos: String(form.get("allowed_repos") ?? "").split(/[\s,]+/).filter(Boolean),
      default_branch: form.get("default_branch") || "main",
      write_enabled: form.get("write_enabled") === "on",
      enabled: true,
    });
    event.currentTarget.reset();
  }

  return (
    <Card>
      <CardHeader
        title="GitHub"
        description="Lets engineering agents read and change allowed repositories on work branches. Opening, merging and deleting always need your approval; main/master can never be written directly."
        action={<StatusBadge status={integration?.status ?? "not_configured"} />}
      />
      <form onSubmit={submit} className="space-y-4 border-t border-border px-5 py-5">
        {(config.allowed_repos?.length ?? 0) > 0 && (
          <div className="flex flex-wrap gap-2">
            {config.allowed_repos?.map((repo) => (
              <Badge key={repo}>{repo}</Badge>
            ))}
            <Badge tone={config.write_enabled ? "warning" : "neutral"}>{config.write_enabled ? "Write enabled" : "Read only"}</Badge>
          </div>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Personal access token"
            htmlFor="token"
            hint={
              integration?.has_secret ? (
                <span className="inline-flex items-center gap-1.5">
                  <Lock className="size-3.5 text-success" /> Saved, encrypted · ending in <span className="font-mono">{integration.secret_last4}</span>
                </span>
              ) : (
                "Fine-grained token limited to the repositories below (Contents + Pull requests)."
              )
            }
          >
            <Input id="token" name="token" type="password" autoComplete="off" placeholder={integration?.has_secret ? "Leave empty to keep the saved token" : "github_pat_…"} disabled={!org.canManage} />
          </Field>
          <Field label="Allowed repositories" htmlFor="allowed_repos" hint="owner/name, separated by commas. Agents cannot access anything else.">
            <Input id="allowed_repos" name="allowed_repos" defaultValue={(config.allowed_repos ?? ["Karim12333/byterootlabs"]).join(", ")} disabled={!org.canManage} />
          </Field>
          <Field label="Default branch" htmlFor="default_branch" hint="Protected like main/master.">
            <Input id="default_branch" name="default_branch" defaultValue={config.default_branch ?? "main"} disabled={!org.canManage} />
          </Field>
          <label className="flex items-center gap-2 self-end pb-2 text-sm">
            <input type="checkbox" name="write_enabled" defaultChecked={config.write_enabled ?? false} disabled={!org.canManage} className="size-4 accent-[var(--accent)]" />
            Allow agents to create branches and commit
          </label>
        </div>
        {integration?.last_checked_at && (
          <p className="text-xs text-muted">
            Last checked {dateTime(integration.last_checked_at)}: {integration.health_message}
          </p>
        )}
        {message && <p className="text-[13px] text-success">{message}</p>}
        <FormError message={save.error?.message ?? test.error?.message ?? remove.error?.message} />
        {org.canManage && (
          <div className="flex flex-wrap gap-2">
            <Button type="submit" variant="primary" loading={save.isPending}>
              Save GitHub
            </Button>
            <Button type="button" onClick={() => test.mutate()} loading={test.isPending} disabled={!integration?.has_secret}>
              Test connection
            </Button>
            {integration?.has_secret && (
              <Button type="button" variant="danger" onClick={() => window.confirm("Remove the GitHub token?") && remove.mutate()}>
                Remove integration
              </Button>
            )}
          </div>
        )}
      </form>
    </Card>
  );
}
