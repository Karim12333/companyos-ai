"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { AuthLayout } from "@/components/auth-layout";
import { Button } from "@/components/ui/button";
import { Field, FormError, Input } from "@/components/ui/form";
import { api } from "@/lib/api";
import { useAuthActions } from "@/lib/session";
import type { Me } from "@/lib/types";

export default function SignupPage() {
  const router = useRouter();
  const { onAuthenticated } = useAuthActions();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setLoading(true);
    setError(null);
    try {
      const me = await api<Me>("/auth/signup", {
        json: {
          full_name: form.get("full_name"),
          organization_name: form.get("organization_name"),
          email: form.get("email"),
          password: form.get("password"),
        },
      });
      await onAuthenticated(me);
      router.replace(`/${me.organizations[0].slug}/headquarters`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Sign up failed");
      setLoading(false);
    }
  }

  return (
    <AuthLayout
      title="Create your organization"
      subtitle="You'll start with a Software / AI Company: 5 departments and 9 specialist agents."
    >
      <form onSubmit={submit} className="space-y-4">
        <Field label="Your name" htmlFor="full_name">
          <Input id="full_name" name="full_name" autoComplete="name" required autoFocus />
        </Field>
        <Field label="Organization name" htmlFor="organization_name">
          <Input id="organization_name" name="organization_name" required minLength={2} />
        </Field>
        <Field label="Work email" htmlFor="email">
          <Input id="email" name="email" type="email" autoComplete="email" required />
        </Field>
        <Field label="Password" htmlFor="password" hint="At least 10 characters.">
          <Input id="password" name="password" type="password" autoComplete="new-password" minLength={10} required />
        </Field>
        <FormError message={error} />
        <Button type="submit" variant="primary" className="w-full" loading={loading}>
          Create organization
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted">
        Already have an account?{" "}
        <Link href="/login" className="font-medium text-ink underline-offset-2 hover:underline">
          Sign in
        </Link>
      </p>
    </AuthLayout>
  );
}
