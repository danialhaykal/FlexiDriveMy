import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatFigure } from "./StatFigure";

describe("StatFigure", () => {
  it("shows the label over the value exactly as given, with its suffix", () => {
    render(<StatFigure label="Monthly" value="RM 7,257.38" suffix="/ month" size="money" />);

    expect(screen.getByText("Monthly")).toBeInTheDocument();
    const value = screen.getByText("RM 7,257.38");
    expect(value).toHaveClass("tabular-nums", "text-money");
    expect(value).toHaveTextContent("RM 7,257.38/ month");
    expect(screen.getByText("/ month")).toHaveClass("text-ink-muted");
  });

  it.each([
    ["money-sm", "text-money-sm"],
    ["default", "text-body"],
  ] as const)("uses the %s size", (size, expectedClass) => {
    render(<StatFigure label="Upfront" value="RM 26,780.00" size={size} />);

    expect(screen.getByText("RM 26,780.00")).toHaveClass(expectedClass);
  });
});
