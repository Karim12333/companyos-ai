import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RiskBadge, StatusBadge } from "@/components/ui/badge";

describe("badges", () => {
  it("labels statuses for humans", () => {
    render(<StatusBadge status="WAITING_FOR_APPROVAL" />);
    expect(screen.getByText("Awaiting approval")).toBeInTheDocument();
  });

  it("shows risk levels with text, never color alone", () => {
    render(<RiskBadge level="3" />);
    expect(screen.getByText("Level 3 · Human approval")).toBeInTheDocument();
  });
});
