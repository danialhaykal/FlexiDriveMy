import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { NegativeEquityChart } from "./NegativeEquityChart";
import type { MonthlyForecastPoint } from "../../types/depreciation";

const FORECAST: MonthlyForecastPoint[] = [
  { month: 0, predicted_resale_value: "400000.00", hp_outstanding_balance: "360000.00" },
  { month: 1, predicted_resale_value: "397333.33", hp_outstanding_balance: "350000.00" },
];

describe("NegativeEquityChart", () => {
  it("renders without crashing and plots both series with the design-token colors", () => {
    const { container } = render(
      <NegativeEquityChart monthlyForecast={FORECAST} crossoverMonth={null} shortfallAmount={null} />,
    );

    const lines = container.querySelectorAll("path.recharts-line-curve");
    expect(lines).toHaveLength(2);
    const strokes = Array.from(lines).map((line) => line.getAttribute("stroke"));
    expect(strokes).toContain("var(--color-primary-600)");
    expect(strokes).toContain("var(--color-danger-600)");
  });

  // --- QA audit L17 -----------------------------------------------------

  it("renders a legend naming both series, not just color-coded lines", () => {
    render(<NegativeEquityChart monthlyForecast={FORECAST} crossoverMonth={null} shortfallAmount={null} />);

    expect(screen.getByText("Predicted resale value")).toBeInTheDocument();
    // Run 1: the balance is the reducing-balance amount to settle, and says so.
    expect(screen.getByText("Amount to settle (estimate)")).toBeInTheDocument();
    expect(screen.queryByText("Remaining loan balance")).not.toBeInTheDocument();
  });

  it("explains the balance is a reducing-balance settlement estimate, not the old straight-line one", () => {
    render(<NegativeEquityChart monthlyForecast={FORECAST} crossoverMonth={null} shortfallAmount={null} />);

    expect(
      screen.getByText(
        "The remaining loan balance is an estimate of the amount needed to settle the loan, using the reducing-balance method that the Hire-Purchase (Amendment) Act 2026 requires for new loans. Your lender's settlement letter is the final figure.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/straight-line/i)).not.toBeInTheDocument();
  });

  it("omits the crossover callout when there is no crossover", () => {
    render(<NegativeEquityChart monthlyForecast={FORECAST} crossoverMonth={null} shortfallAmount={null} />);

    expect(screen.queryByText(/negative equity begins/i)).not.toBeInTheDocument();
  });

  it("shows the crossover month and shortfall amount when there is one", () => {
    render(
      <NegativeEquityChart
        monthlyForecast={FORECAST}
        crossoverMonth={42}
        shortfallAmount="15000.00"
      />,
    );

    const callout = screen.getByText(/negative equity begins at month 42/i);
    expect(callout).toBeInTheDocument();
    expect(callout).toHaveTextContent("RM 15,000.00");
  });
});
