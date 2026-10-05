"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card, PageHeader } from "@/components/ui/card";
import { Field, FormError, Input, Select, Textarea } from "@/components/ui/form";
import { useOrgMutation } from "@/lib/hooks";
import { useOrg, useOrgQuery } from "@/lib/session";
import type { Objective, Project } from "@/lib/types";

const EXAMPLE =
  "Research and prepare a launch plan for an AI meeting assistant. Include market research, product definition, technical architecture, marketing messaging and an executive recommendation. Do not publish anything without my approval.";

export default function NewObjectivePage() {
  const org = useOrg();
  const router = useRouter();
  const { data: projects } = useOrgQuery<Project[]>(["projects"], "/projects");
  const [warning, setWarning] = useState<string | null>(null);
  const create = useOrgMutation<Record<string, unknown>, { objective: Objective; workflow_error: string | null }>(
    (json) => ({ path: "/objectives", json }),
    {
      onSuccess: (result) => {
        if (result.workflow_error) setWarning(result.workflow_error);
        else router.push(org.href(`/objectives/${result.objective.id}`));
      },
    },
  );

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const budget = String(form.get("budget_usd") ?? "");
    const target = String(form.get("target_date") ?? "");
    create.mutate({
      title: form.get("title"),
      instruction: form.get("instruction"),
      context: form.get("context") || "",
      priority: form.get("priority"),
      project_id: form.get("project_id") || null,
      external_actions: form.get("external_actions"),
      budget_usd: budget ? Number(budget) : null,
      target_date: target ? new Date(target).toISOString() : null,
    });
  }

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="New objective"
        description="Describe the outcome you want. The Chief of Staff will plan it, assign departments and run the work, overnight if needed."
      />
      <Card className="p-5 sm:p-6">
        <form onSubmit={submit} className="space-y-5">
          <Field label="Title" htmlFor="title">
            <Input id="title" name="title" required minLength={3} maxLength={300} placeholder="AI meeting assistant — launch plan" />
          </Field>
          <Field label="Instruction" htmlFor="instruction" hint="Be specific about deliverables, constraints and what needs your approval.">
            <Textarea id="instruction" name="instruction" required minLength={10} rows={6} placeholder={EXAMPLE} />
          </Field>
          <Field label="Context (optional)" htmlFor="context" hint="Background the team should know: customers, constraints, prior decisions.">
            <Textarea id="context" name="context" rows={3} />
          </Field>
          <div className="grid gap-5 sm:grid-cols-2">
            <Field label="Priority" htmlFor="priority">
              <Select id="priority" name="priority" defaultValue="normal">
                <option value="low">Low</option>
                <option value="normal">Normal</option>
                <option value="high">High</option>
                <option value="urgent">Urgent</option>
              </Select>
            </Field>
            <Field label="Project" htmlFor="project_id">
              <Select id="project_id" name="project_id" defaultValue="">
                <option value="">No project</option>
                {projects?.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Target date (optional)" htmlFor="target_date">
              <Input id="target_date" name="target_date" type="datetime-local" />
            </Field>
            <Field label="Budget in USD (optional)" htmlFor="budget_usd" hint="Defaults to the organization objective budget.">
              <Input id="budget_usd" name="budget_usd" type="number" min={0} step="0.5" />
            </Field>
          </div>
          <Field
            label="External actions"
            htmlFor="external_actions"
            hint="Publishing, emailing externally and spending are never automatic. Choose whether agents may request them at all."
          >
            <Select id="external_actions" name="external_actions" defaultValue="require_approval">
              <option value="require_approval">Allowed with my approval</option>
              <option value="deny">Blocked entirely for this objective</option>
            </Select>
          </Field>
          <FormError message={create.error?.message ?? warning} />
          <div className="flex justify-end gap-2 pt-1">
            <Button type="button" variant="ghost" onClick={() => router.back()}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={create.isPending}>
              Start objective
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
