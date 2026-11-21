import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { LoadingSkeleton } from "./LoadingSkeleton";

describe("LoadingSkeleton", () => {
  it("renders as a status region and defaults to the block variant", () => {
    render(<LoadingSkeleton />);

    const skeleton = screen.getByRole("status", { name: "Loading" });
    expect(skeleton).toBeInTheDocument();
    expect(skeleton).toHaveAttribute("data-variant", "block");
    expect(skeleton.className).toContain("animate-pulse");
    expect(skeleton.className).toContain("rounded-md");
  });

  it.each<["text" | "circle", string]>([
    ["text", "rounded"],
    ["circle", "rounded-full"],
  ])("applies the %s variant's classes", (variant, expectedClass) => {
    render(<LoadingSkeleton variant={variant} />);

    const skeleton = screen.getByRole("status", { name: "Loading" });
    expect(skeleton).toHaveAttribute("data-variant", variant);
    expect(skeleton.className).toContain(expectedClass);
  });
});
