"use client";

import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { api, ApiError, apiUrl, setCsrfToken } from "@/lib/api";
import type { Me, OrganizationSummary } from "@/lib/types";

let browserQueryClient: QueryClient | undefined;

function getQueryClient() {
  const create = () =>
    new QueryClient({
      defaultOptions: {
        queries: {
          staleTime: 5_000,
          retry: (count, error) => !(error instanceof ApiError && error.status < 500) && count < 2,
        },
      },
    });
  if (typeof window === "undefined") return create();
  browserQueryClient ??= create();
  return browserQueryClient;
}

export function Providers({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={getQueryClient()}>{children}</QueryClientProvider>;
}

export function useMe() {
  const query = useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      const me = await api<Me>("/auth/me");
      setCsrfToken(me.csrf_token);
      return me;
    },
    staleTime: 60_000,
  });
  return query;
}

export function useAuthActions() {
  const client = useQueryClient();
  return {
    async onAuthenticated(me: Me) {
      setCsrfToken(me.csrf_token);
      client.setQueryData(["me"], me);
    },
    async logout() {
      await api("/auth/logout", { method: "POST" });
      setCsrfToken(null);
      client.clear();
    },
  };
}

interface OrgContextValue extends OrganizationSummary {
  path: (suffix?: string) => string;
  href: (suffix?: string) => string;
  canManage: boolean;
  canDecide: boolean;
  canEdit: boolean;
}

const OrgContext = createContext<OrgContextValue | null>(null);

export function OrgProvider({ organization, children }: { organization: OrganizationSummary; children: ReactNode }) {
  const value: OrgContextValue = {
    ...organization,
    path: (suffix = "") => `/orgs/${organization.id}${suffix}`,
    href: (suffix = "") => `/${organization.slug}${suffix}`,
    canManage: organization.role === "owner" || organization.role === "admin",
    canDecide: organization.role === "owner" || organization.role === "admin",
    canEdit: organization.role !== "viewer",
  };
  return <OrgContext.Provider value={value}>{children}</OrgContext.Provider>;
}

export function useOrg(): OrgContextValue {
  const value = useContext(OrgContext);
  if (!value) throw new Error("useOrg must be used inside an organization route");
  return value;
}

export function useOrgQuery<T>(key: unknown[], suffix: string, options: { refetchInterval?: number; enabled?: boolean } = {}) {
  const org = useOrg();
  return useQuery({
    queryKey: ["org", org.id, ...key],
    queryFn: () => api<T>(org.path(suffix)),
    ...options,
  });
}

export type LiveStatus = "connecting" | "live" | "offline";

export function useLiveEvents(organizationId: string): LiveStatus {
  const client = useQueryClient();
  const [status, setStatus] = useState<LiveStatus>("connecting");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const source = new EventSource(apiUrl(`/orgs/${organizationId}/events/stream`), { withCredentials: true });
    // Batch bursts of events into a single refresh of this organization's data
    const refresh = () => {
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => client.invalidateQueries({ queryKey: ["org", organizationId] }), 350);
    };
    source.addEventListener("ready", () => setStatus("live"));
    source.onmessage = refresh;
    source.onerror = () => setStatus("offline");
    source.onopen = () => setStatus("live");
    return () => {
      source.close();
      if (timer.current) clearTimeout(timer.current);
    };
  }, [client, organizationId]);

  return status;
}
