import { Suspense } from "react";

import { PageSkeleton } from "@/components/ui/feedback";

import { ObjectiveDetail } from "./objective-detail";

export default function ObjectivePage() {
  return (
    <Suspense fallback={<PageSkeleton />}>
      <ObjectiveDetail />
    </Suspense>
  );
}
