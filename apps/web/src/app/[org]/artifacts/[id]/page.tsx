"use client";

import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Badge, StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { ErrorState, PageSkeleton, Skeleton } from "@/components/ui/feedback";
import { FormError, Select, Textarea } from "@/components/ui/form";
import { Markdown } from "@/components/ui/markdown";
import { apiText, apiUrl } from "@/lib/api";
import { dateTime, humanize } from "@/lib/format";
import { useAgents, useOrgMutation } from "@/lib/hooks";
import { useOrg, useOrgQuery } from "@/lib/session";
import type { Artifact, ArtifactVersion } from "@/lib/types";

interface ArtifactDetail {
  artifact: Artifact;
  versions: ArtifactVersion[];
  objective: { id: string; title: string } | null;
  task: { id: string; title: string; status: string } | null;
  feedback: { id: string; comment: string; rating: number | null; status: string; created_at: string }[];
}

export default function ArtifactPage() {
  const org = useOrg();
  const { id } = useParams<{ id: string }>();
  const agents = useAgents();
  const [version, setVersion] = useState<number | null>(null);
  const { data, error, isPending } = useOrgQuery<ArtifactDetail>(["artifact", id], `/artifacts/${id}`);
  const current = version ?? data?.artifact.current_version ?? 1;
  const content = useQuery({
    queryKey: ["org", org.id, "artifact-content", id, current],
    queryFn: () => apiText(org.path(`/artifacts/${id}/content?version=${current}`)),
    enabled: Boolean(data),
  });

  if (isPending) return <PageSkeleton />;
  if (error) return <ErrorState error={error} />;
  const { artifact } = data;
  const isMarkdown = artifact.mime_type.includes("markdown") || artifact.filename.endsWith(".md");

  return (
    <div className="space-y-6">
      <div>
        <Link href={org.href("/artifacts")} className="text-[13px] text-muted hover:text-ink">
          Artifacts
        </Link>
        <div className="mt-1 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <h1 className="text-[22px] font-semibold tracking-tight">{artifact.title}</h1>
            <p className="mt-1 text-sm text-muted">
              {artifact.agent_id ? agents.byId.get(artifact.agent_id)?.name : "CEO"} · {artifact.filename}
              {data.objective && (
                <>
                  {" · "}
                  <Link href={org.href(`/objectives/${data.objective.id}`)} className="hover:underline">
                    {data.objective.title}
                  </Link>
                </>
              )}
            </p>
            <div className="mt-2 flex flex-wrap gap-2">
              <StatusBadge status={artifact.review_status} />
              <Badge>{humanize(artifact.kind)}</Badge>
              {artifact.generated_by_mock && <Badge tone="warning">Offline mock output</Badge>}
            </div>
          </div>
          <div className="flex gap-2">
            {data.versions.length > 1 && (
              <Select aria-label="Version" value={current} onChange={(event) => setVersion(Number(event.target.value))} className="w-32">
                {data.versions.map((item) => (
                  <option key={item.id} value={item.version}>
                    Version {item.version}
                  </option>
                ))}
              </Select>
            )}
            <a
              href={apiUrl(org.path(`/artifacts/${id}/content?version=${current}&download=true`))}
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-border bg-surface px-3.5 text-sm font-medium hover:bg-surface-hover"
            >
              <Download className="size-4" /> Download
            </a>
          </div>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[1fr_320px]">
        <Card className="min-w-0 px-6 py-6 sm:px-10 sm:py-8">
          {content.isPending ? (
            <div className="space-y-3">
              <Skeleton className="h-7 w-2/3" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-5/6" />
            </div>
          ) : content.error ? (
            <ErrorState error={content.error} />
          ) : isMarkdown ? (
            <Markdown>{content.data}</Markdown>
          ) : (
            <pre className="overflow-x-auto font-mono text-[13px] whitespace-pre-wrap">{content.data}</pre>
          )}
        </Card>
        <div className="space-y-6">
          <Card>
            <CardHeader title="Versions" />
            <ul className="divide-y divide-border border-t border-border">
              {data.versions.map((item) => (
                <li key={item.id} className="px-5 py-2.5 text-[13px]">
                  <div className="flex justify-between">
                    <span className="font-medium">v{item.version}</span>
                    <span className="text-muted">{dateTime(item.created_at)}</span>
                  </div>
                  <p className="mt-0.5 truncate font-mono text-[11px] text-faint" title={item.checksum_sha256}>
                    sha256 {item.checksum_sha256.slice(0, 16)}… · {(item.size_bytes / 1024).toFixed(1)} KB
                  </p>
                </li>
              ))}
            </ul>
          </Card>
          <FeedbackCard artifactId={artifact.id} feedback={data.feedback} />
        </div>
      </div>
    </div>
  );
}

function FeedbackCard({ artifactId, feedback }: { artifactId: string; feedback: ArtifactDetail["feedback"] }) {
  const org = useOrg();
  const [comment, setComment] = useState("");
  const create = useOrgMutation<string>((text) => ({ path: "/feedback", json: { comment: text, artifact_id: artifactId } }), {
    onSuccess: () => setComment(""),
  });
  function submit(event: FormEvent) {
    event.preventDefault();
    if (comment.trim()) create.mutate(comment.trim());
  }
  return (
    <Card>
      <CardHeader title="Feedback" description="Feedback can be promoted to a lasting company preference in Knowledge." />
      <div className="space-y-3 border-t border-border px-5 py-4">
        {feedback.map((item) => (
          <div key={item.id} className="rounded-lg bg-surface-muted px-3 py-2 text-[13px]">
            <p>{item.comment}</p>
            <p className="mt-0.5 text-xs text-muted">
              {dateTime(item.created_at)} · {item.status}
            </p>
          </div>
        ))}
        {org.canEdit && (
          <form onSubmit={submit} className="space-y-2">
            <Textarea aria-label="Feedback" rows={3} value={comment} onChange={(event) => setComment(event.target.value)} placeholder="e.g. Too corporate. Be more technical and concise." />
            <FormError message={create.error?.message} />
            <Button type="submit" size="sm" loading={create.isPending} disabled={!comment.trim()}>
              Add feedback
            </Button>
          </form>
        )}
      </div>
    </Card>
  );
}
