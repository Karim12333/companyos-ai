"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { AuthLayout } from "@/components/auth-layout";
import { Button } from "@/components/ui/button";
import { Field, FormError, Input } from "@/components/ui/form";
import { api } from "@/lib/api";
import { useMe } from "@/lib/session";
import type { OrganizationSummary } from "@/lib/types";

export default function NewOrganizationPage() {
  const router = useRouter();
  const client = useQueryClient();
  useMe();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const organization = await api<OrganizationSummary>("/orgs", {
        json: { name: new FormData(event.currentTarget).get("name"), template_key: "software_ai_company" },
      });
      await client.invalidateQueries({ queryKey: ["me"] });
      router.push(`/${organization.slug}/headquarters`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not create organization");
      setLoading(false);
    }
  }

  return (
    <AuthLayout title="New organization" subtitle="Fully isolated from your other organizations: its own agents, data, keys and budget.">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Organization name" htmlFor="name">
          <Input id="name" name="name" required minLength={2} autoFocus />
        </Field>
        <Field label="Template" htmlFor="template" hint="More templates (marketing agency, consultancy, research team) are planned.">
          <Input id="template" value="Software / AI Company" disabled readOnly />
        </Field>
        <FormError message={error} />
        <Button type="submit" variant="primary" className="w-full" loading={loading}>
          Create organization
        </Button>
        <Button type="button" variant="ghost" className="w-full" onClick={() => router.back()}>
          Cancel
        </Button>
      </form>
    </AuthLayout>
  );
}
