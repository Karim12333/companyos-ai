import { GitBranch, GitCommit, GitPullRequest } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardHeader } from "@/components/ui/card";
import { clock } from "@/lib/format";

export interface CodeChange {
  event: string;
  summary: string;
  created_at: string;
  repo?: string;
  branch?: string;
  sha?: string;
  files?: string[];
  pr_url?: string;
  pr_number?: number;
  pr_state?: string;
  checks?: { name: string; status: string; conclusion: string | null }[];
}

const ICON = { commit: GitCommit, pr_opened: GitPullRequest, pr_merged: GitPullRequest };

export function CodeChanges({ changes }: { changes: CodeChange[] }) {
  if (!changes.length) return null;
  return (
    <Card>
      <CardHeader title="Code changes" description="Repository work done by engineering agents." />
      <ul className="divide-y divide-border border-t border-border">
        {changes.map((change, index) => {
          const Icon = ICON[change.event as keyof typeof ICON] ?? GitBranch;
          return (
            <li key={index} className="flex gap-3 px-5 py-3 text-[13px]">
              <Icon className="mt-0.5 size-4 shrink-0 text-muted" aria-hidden />
              <div className="min-w-0 flex-1 space-y-1">
                <p className="text-ink">{change.summary}</p>
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                  {change.repo && <span className="font-mono">{change.repo}</span>}
                  {change.branch && <Badge>{change.branch}</Badge>}
                  {change.sha && <span className="font-mono">{change.sha.slice(0, 10)}</span>}
                  {change.pr_url && (
                    <a href={change.pr_url} target="_blank" rel="noopener noreferrer" className="text-accent hover:underline">
                      PR #{change.pr_number} · {change.pr_state}
                    </a>
                  )}
                </div>
                {change.files && <p className="truncate font-mono text-[11.5px] text-faint">{change.files.join(", ")}</p>}
                {change.checks && (
                  <div className="flex flex-wrap gap-1.5">
                    {change.checks.length === 0 && <span className="text-xs text-muted">No CI checks reported</span>}
                    {change.checks.map((check) => (
                      <Badge key={check.name} tone={check.conclusion === "success" ? "success" : check.conclusion ? "danger" : "info"}>
                        {check.name}: {check.conclusion ?? check.status}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
              <span className="text-xs text-faint">{clock(change.created_at)}</span>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
