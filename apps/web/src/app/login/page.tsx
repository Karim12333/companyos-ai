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

export default function LoginPage() {
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
      const me = await api<Me>("/auth/login", { json: { email: form.get("email"), password: form.get("password") } });
      await onAuthenticated(me);
      const next = new URLSearchParams(window.location.search).get("next");
      const first = me.organizations[0];
      router.replace(next?.startsWith("/") ? next : first ? `/${first.slug}/headquarters` : "/new-organization");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Sign in failed");
      setLoading(false);
    }
  }

  return (
    <AuthLayout title="Sign in" subtitle="Welcome back. Your organization kept working.">
      <form onSubmit={submit} className="space-y-4">
        <Field label="Email" htmlFor="email">
          <Input id="email" name="email" type="email" autoComplete="email" required autoFocus />
        </Field>
        <Field label="Password" htmlFor="password">
          <Input id="password" name="password" type="password" autoComplete="current-password" required />
        </Field>
        <FormError message={error} />
        <Button type="submit" variant="primary" className="w-full" loading={loading}>
          Sign in
        </Button>
      </form>
      <p className="mt-6 text-center text-sm text-muted">
        New to CompanyOS?{" "}
        <Link href="/signup" className="font-medium text-ink underline-offset-2 hover:underline">
          Create an organization
        </Link>
      </p>
    </AuthLayout>
  );
}
