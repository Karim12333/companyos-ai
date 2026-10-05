"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Skeleton } from "@/components/ui/feedback";
import { useMe } from "@/lib/session";

export default function Home() {
  const router = useRouter();
  const { data, error } = useMe();

  useEffect(() => {
    if (error) router.replace("/login");
    else if (data) router.replace(data.organizations[0] ? `/${data.organizations[0].slug}/headquarters` : "/new-organization");
  }, [data, error, router]);

  return (
    <main className="flex min-h-screen items-center justify-center">
      <Skeleton className="h-6 w-40" />
    </main>
  );
}
