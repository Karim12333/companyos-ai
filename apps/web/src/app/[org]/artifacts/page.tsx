"use client";

import { FileText } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge, StatusBadge } from "@/components/ui/badge";
import { Card, PageHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/ui/feedback";
import { Select } from "@/components/ui/form";
import { humanize, timeAgo } from "@/lib/format";
import { useAgents } from "@/lib/hooks";
import { useOrg, useOrgQuery } from "@/lib/session";
import type { Artifact } from "@/lib/types";

export default function ArtifactsPage() {
  const org = useOrg();
  const agents = useAgents();
  const [agentId, setAgentId] = useState("");
  const { data, error, isPending } = useOrgQuery<Artifact[]>(["artifacts", agentId], `/artifacts${agentId ? `?agent_id=${agentId}` : ""}`);

  return (
    <div>
      <PageHeader
        title="Artifacts"
        description="Deliverables produced by your organization, versioned and reviewed."
        actions={
          <Select aria-label="Filter by agent" value={agentId} onChange={(event) => setAgentId(event.target.value)} className="w-48">
            <option value="">All agents</option>
            {agents.data?.map((agent) => (
              <option key={agent.id} value={agent.id}>
                {agent.name}
              </option>
            ))}
          </Select>
        }
      />
      {isPending ? (
        <PageSkeleton />
      ) : error ? (
        <ErrorState error={error} />
      ) : data.length === 0 ? (
        <Card>
          <EmptyState title="No artifacts yet" description="Agents save their deliverables here as they work." icon={<FileText className="size-5" />} />
        </Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {data.map((artifact) => (
            <Link key={artifact.id} href={org.href(`/artifacts/${artifact.id}`)}>
              <Card className="flex h-full flex-col p-4 transition-colors hover:border-border-strong">
                <div className="flex items-start gap-3">
                  <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-surface-muted text-muted">
                    <FileText className="size-4" />
                  </span>
                  <div className="min-w-0">
                    <p className="line-clamp-2 text-sm font-medium">{artifact.title}</p>
                    <p className="mt-0.5 truncate text-xs text-muted">{artifact.filename}</p>
                  </div>
                </div>
                <div className="mt-auto flex flex-wrap items-center gap-2 pt-4">
                  <StatusBadge status={artifact.review_status} />
                  <Badge>{humanize(artifact.kind)}</Badge>
                  <span className="ml-auto text-xs text-faint">
                    {artifact.agent_id ? agents.byId.get(artifact.agent_id)?.name : "CEO"} · v{artifact.current_version} · {timeAgo(artifact.updated_at)}
                  </span>
                </div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
