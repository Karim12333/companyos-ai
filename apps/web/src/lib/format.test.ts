import { describe, expect, it } from "vitest";

import { duration, humanize, initials, usd } from "@/lib/format";

describe("format helpers", () => {
  it("formats durations", () => {
    expect(duration(42)).toBe("42s");
    expect(duration(125)).toBe("2m 5s");
    expect(duration(3 * 3600 + 42 * 60)).toBe("3h 42m");
    expect(duration(null)).toBe("—");
  });

  it("formats money and labels", () => {
    expect(usd(0.0123)).toBe("$0.0123");
    expect(usd(12.5)).toBe("$12.50");
    expect(humanize("WAITING_FOR_APPROVAL")).toBe("Waiting for approval");
    expect(initials("Market Researcher")).toBe("MR");
  });
});
