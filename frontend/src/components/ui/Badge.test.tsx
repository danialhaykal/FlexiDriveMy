import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Badge } from "./Badge";
import type { Tone } from "./tokens";

describe("Badge", () => {
  it("defaults to the neutral tone", () => {
    render(<Badge>Service degraded</Badge>);

    const badge = screen.getByText("Service degraded");
    expect(badge).toHaveAttribute("data-tone", "neutral");
    expect(badge.className).toContain("bg-surface-subtle");
  });

  it("uses slate-600 text on the neutral badge, for at least 4.5:1 at 12 px (run 1 fix batch 5)", () => {
    render(<Badge>Archived</Badge>);

    const badge = screen.getByText("Archived");
    // slate-500 (ink-muted) on slate-100 measured 4.35:1; slate-600 is 6.90:1.
    expect(badge.className).toContain("text-slate-600");
    expect(badge.className).not.toContain("text-ink-muted");
  });

  it.each<[Tone, string]>([
    ["positive", "bg-positive-50"],
    ["warning", "bg-warning-50"],
    ["danger", "bg-danger-50"],
    ["recommended", "bg-primary-600"],
    ["estimate", "bg-amber-50"],
  ])("applies the %s tone's classes", (tone, expectedClass) => {
    render(<Badge tone={tone}>Status</Badge>);

    const badge = screen.getByText("Status");
    expect(badge).toHaveAttribute("data-tone", tone);
    expect(badge.className).toContain(expectedClass);
  });
});
