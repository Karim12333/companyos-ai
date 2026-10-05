"use client";

import { Check, X } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { FormError, Input } from "@/components/ui/form";
import { useOrgMutation } from "@/lib/hooks";
import { useOrg } from "@/lib/session";
import type { Approval } from "@/lib/types";

export function ApprovalActions({ approval, withNote }: { approval: Approval; withNote?: boolean }) {
  const org = useOrg();
  const [note, setNote] = useState("");
  const decide = useOrgMutation<boolean>((approve) => ({
    path: `/approvals/${approval.id}/decision`,
    json: { approve, note },
  }));

  if (approval.status !== "PENDING") return null;
  if (!org.canDecide) return <p className="text-xs text-muted">Only owners and admins can decide approvals.</p>;

  return (
    <div className="space-y-2">
      {withNote && (
        <Input
          aria-label="Decision note"
          placeholder="Optional note for the agent"
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      )}
      <div className="flex gap-2">
        <Button size="sm" variant="success" loading={decide.isPending && decide.variables === true} disabled={decide.isPending} onClick={() => decide.mutate(true)}>
          <Check className="size-3.5" /> Approve
        </Button>
        <Button size="sm" variant="danger" loading={decide.isPending && decide.variables === false} disabled={decide.isPending} onClick={() => decide.mutate(false)}>
          <X className="size-3.5" /> Reject
        </Button>
      </div>
      <FormError message={decide.error?.message} />
    </div>
  );
}
