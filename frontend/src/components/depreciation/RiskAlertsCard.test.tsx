import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { RiskAlertsCard } from "./RiskAlertsCard";

describe("RiskAlertsCard", () => {
  it("renders nothing when there are no alerts", () => {
    const { container } = render(<RiskAlertsCard alerts={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  // Live-walkthrough finding: a scenario saved before Batch 6C added
  // risk_alerts has no such key at all in its stored payload - `alerts`
  // is genuinely `undefined`, not `[]`, and previously threw reading
  // `.length` on it.
  it("renders nothing (not a crash) when alerts is undefined", () => {
    const { container } = render(<RiskAlertsCard alerts={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a warning-styled alert for negative equity", () => {
    render(
      <RiskAlertsCard
        alerts={[
          {
            code: "negative_equity_within_horizon",
            severity: "warning",
            message: "Predicted resale value falls below the outstanding loan balance starting month 16.",
          },
        ]}
      />,
    );

    expect(screen.getByText("Warning")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Predicted resale value falls below the outstanding loan balance starting month 16.",
      ),
    ).toBeInTheDocument();
  });

  it("renders an info-styled alert for a declared-mileage mismatch, distinct from a warning", () => {
    render(
      <RiskAlertsCard
        alerts={[
          {
            code: "declared_mileage_mismatch",
            severity: "info",
            message: "This estimate uses the 'Standard' mileage band, but your saved profile declares 'Very High'.",
          },
        ]}
      />,
    );

    expect(screen.getByText("Info")).toBeInTheDocument();
    expect(screen.queryByText("Warning")).not.toBeInTheDocument();
  });

  it("renders both alerts when both conditions fire at once", () => {
    render(
      <RiskAlertsCard
        alerts={[
          { code: "negative_equity_within_horizon", severity: "warning", message: "Equity warning." },
          { code: "declared_mileage_mismatch", severity: "info", message: "Mileage mismatch." },
        ]}
      />,
    );

    expect(screen.getByText("Equity warning.")).toBeInTheDocument();
    expect(screen.getByText("Mileage mismatch.")).toBeInTheDocument();
  });
});
