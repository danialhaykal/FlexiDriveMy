import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Card } from "./Card";

describe("Card", () => {
  it("renders its children with default (md) padding", () => {
    render(<Card>Comparison summary</Card>);

    const card = screen.getByText("Comparison summary");
    expect(card).toBeInTheDocument();
    expect(card).toHaveAttribute("data-padding", "md");
    expect(card.className).toContain("p-6");
  });

  it("omits padding when padding='none'", () => {
    render(<Card padding="none">Edge to edge</Card>);

    const card = screen.getByText("Edge to edge");
    expect(card.className).not.toContain("p-6");
  });

  it("rings a highlighted card in indigo, and leaves a default card on the plain border", () => {
    render(
      <>
        <Card tone="highlight">Recommended item</Card>
        <Card>Plain item</Card>
      </>,
    );

    expect(screen.getByText("Recommended item")).toHaveClass("ring-1", "ring-primary-600");
    expect(screen.getByText("Plain item")).toHaveClass("border-border");
    expect(screen.getByText("Plain item")).not.toHaveClass("ring-1");
  });
});
