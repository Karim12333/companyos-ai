"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, PageHeader } from "@/components/ui/card";
import { EmptyState, ErrorState, PageSkeleton } from "@/components/ui/feedback";
import { Field, FormError, Input, Textarea } from "@/components/ui/form";
import { useOrgMutation } from "@/lib/hooks";
import { useOrg, useOrgQuery } from "@/lib/session";
import type { Project } from "@/lib/types";

export default function ProjectsPage() {
  const org = useOrg();
  const [creating, setCreating] = useState(false);
  const { data, error, isPending } = useOrgQuery<Project[]>(["projects"], "/projects");
  const create = useOrgMutation<Record<string, unknown>>((json) => ({ path: "/projects", json }), {
    onSuccess: () => setCreating(false),
  });

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    create.mutate({
      name: form.get("name"),
      description: form.get("description"),
      target_date: form.get("target_date") || null,
    });
  }

  return (
    <div>
      <PageHeader
        title="Projects"
        description="Group related objectives, artifacts and knowledge."
        actions={
          org.canEdit && (
            <Button variant="primary" onClick={() => setCreating(true)}>
              <Plus className="size-4" /> New project
            </Button>
          )
        }
      />
      {creating && (
        <Card className="mb-6 p-5">
          <form onSubmit={submit} className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-[1fr_200px]">
              <Field label="Name" htmlFor="name">
                <Input id="name" name="name" required minLength={2} autoFocus />
              </Field>
              <Field label="Target date" htmlFor="target_date">
                <Input id="target_date" name="target_date" type="date" />
              </Field>
            </div>
            <Field label="Description" htmlFor="description">
              <Textarea id="description" name="description" rows={3} />
            </Field>
            <FormError message={create.error?.message} />
            <div className="flex gap-2">
              <Button type="submit" variant="primary" loading={create.isPending}>
                Create project
              </Button>
              <Button type="button" variant="ghost" onClick={() => setCreating(false)}>
                Cancel
              </Button>
            </div>
          </form>
        </Card>
      )}
      {isPending ? (
        <PageSkeleton />
      ) : error ? (
        <ErrorState error={error} />
      ) : data.length === 0 ? (
        <Card>
          <EmptyState title="No projects yet" description="Projects keep related objectives and their outputs together." />
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {data.map((project) => (
            <Link key={project.id} href={org.href(`/projects/${project.id}`)}>
              <Card className="h-full p-5 transition-colors hover:border-border-strong">
                <div className="flex items-start justify-between gap-3">
                  <h2 className="text-[15px] font-semibold">{project.name}</h2>
                  <StatusBadge status={project.status} />
                </div>
                <p className="mt-1 line-clamp-2 text-[13px] text-muted">{project.description || "No description"}</p>
                <p className="mt-4 text-xs text-faint">
                  {project.objective_count ?? 0} objective(s){project.target_date && ` · due ${project.target_date}`}
                </p>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
