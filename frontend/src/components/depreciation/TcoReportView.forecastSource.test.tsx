import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { TcoReportView } from "./TcoReportView";
import type { TcoReport } from "../../types/depreciation";

// Run 2 fix batch 3 (A14, X1): the badge follows the server's forecast_source. A car
// the model doesn't cover shows a neutral "Estimated curve"; the amber "Degraded" is
// for a model that isn't available, and for a snapshot saved before forecast_source
// existed. The sentence beside the badge is the server's own, shown as sent.

const EV_REASON =
  "Showing an estimated depreciation curve from planning assumptions. The machine-learning forecast does not cover electric cars yet: the training data has none.";
const OFF_REASON =
  "Showing an estimated depreciation curve from planning assumptions. The machine-learning forecast is switched off until a model passes the accuracy check.";

function makeReport(overrides: Partial<TcoReport> = {}): TcoReport {
  return {
    vehicle_id: 5, tenure_months: 60, mileage_band: "standard", downpayment: "26580.00", hp_monthly: "4545.18",
    model_degraded: false, degraded_reason: null,
    monthly_forecast: [
      { month: 0, predicted_resale_value: "265800.00", hp_outstanding_balance: "239220.00" },
      { month: 1, predicted_resale_value: "262000.00", hp_outstanding_balance: "235000.00" },
    ],
    tco_gross: "338397.80", tco_net: "203742.51",
    road_tax_annual: "379.00", insurance_annual: "4784.40", maintenance_annual: "2658.00",
    negative_equity_crossover_month: null, negative_equity_shortfall_amount: null, resale_value_explanation: null,
    risk_radar: {}, radar_unavailable: {}, cumulative_cash_flow: [], contract_checklist: null, risk_alerts: [],
    ...overrides,
  };
}

describe("TcoReportView forecast badge", () => {
  it("shows a neutral 'Estimated curve' for a car the model doesn't cover, with the server's reason", () => {
    render(
      <TcoReportView
        report={makeReport({ model_degraded: true, degraded_reason: EV_REASON, forecast_source: "estimated_curve_unsupported" })}
      />,
    );

    const badge = screen.getByText("Estimated curve");
    expect(badge).toHaveAttribute("data-tone", "neutral");
    expect(screen.getByText(EV_REASON)).toBeInTheDocument();
    expect(screen.queryByText("Degraded")).not.toBeInTheDocument();
  });

  it("keeps the amber 'Degraded' for a model that isn't available", () => {
    render(
      <TcoReportView
        report={makeReport({ model_degraded: true, degraded_reason: OFF_REASON, forecast_source: "model_unavailable" })}
      />,
    );

    expect(screen.getByText("Degraded")).toHaveAttribute("data-tone", "warning");
    expect(screen.getByText(OFF_REASON)).toBeInTheDocument();
    expect(screen.queryByText("Estimated curve")).not.toBeInTheDocument();
  });

  it("keeps today's behaviour for an older snapshot with no forecast_source", () => {
    const old = makeReport({ model_degraded: true, degraded_reason: OFF_REASON });
    expect("forecast_source" in old).toBe(false);

    const { container } = render(<TcoReportView report={old} />);

    expect(screen.getByText("Degraded")).toHaveAttribute("data-tone", "warning");
    expect(screen.queryByText("Estimated curve")).not.toBeInTheDocument();
    expect(container.textContent).not.toContain("undefined");
  });

  it("shows neither badge when the machine-learning model produced the curve", () => {
    render(<TcoReportView report={makeReport({ forecast_source: "ml_model" })} />);

    expect(screen.queryByText("Degraded")).not.toBeInTheDocument();
    expect(screen.queryByText("Estimated curve")).not.toBeInTheDocument();
  });
});
