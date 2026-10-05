"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { useOrg, useOrgQuery } from "@/lib/session";
import type { Agent, Department } from "@/lib/types";

export function useAgents() {
  const query = useOrgQuery<Agent[]>(["agents"], "/agents");
  const byId = new Map((query.data ?? []).map((agent) => [agent.id, agent]));
  return { ...query, byId };
}

export function useDepartments() {
  const query = useOrgQuery<Department[]>(["departments"], "/departments");
  const byId = new Map((query.data ?? []).map((department) => [department.id, department]));
  return { ...query, byId };
}

// Mutations refresh all of this organization's cached data on success
export function useOrgMutation<TBody, TResult = unknown>(
  build: (body: TBody) => { path: string; method?: string; json?: unknown },
  options: { onSuccess?: (result: TResult) => void } = {},
) {
  const org = useOrg();
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: TBody) => {
      const request = build(body);
      return api<TResult>(org.path(request.path), { method: request.method ?? "POST", json: request.json });
    },
    onSuccess: async (result) => {
      await client.invalidateQueries({ queryKey: ["org", org.id] });
      options.onSuccess?.(result);
    },
  });
}
