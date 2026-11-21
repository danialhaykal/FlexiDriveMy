import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { TcoReportView } from "./TcoReportView";
import type { PathwayTco, PathwayTcoEntry, TcoReport } from "../../types/depreciation";

// Run 2 fix batch 2 (E3, C6, E5): the two server-built sentences on the TCO tab.
// They are shown as-is, in one place each, and an older saved snapshot (which
// has neither key) renders exactly as before.

const VIEWS_NOTE =
  "At month 60, the lender's GFV residual for this car is RM 93,030.00 (35% of the price), while the predicted market value is RM 134,655.29 (50.7% of the price). The GFV figure is a guaranteed buy-back price that lenders set conservatively; the prediction is the expected market price, so the two are different things and can differ. Subscription fees are priced on the same conservative residual as GFV.";
const FORECAST_NOTE =
  "Predicted resale value is a machine-learning estimate for this car's brand tier, age and mileage, scaled to this car's own price. Cars in the same brand tier share the same shape. Typical error is about 16% of the price.";

function entry(overrides: Partial<PathwayTcoEntry> = {}): PathwayTcoEntry {
  return {
    available: true, unavailable_reason: null, horizon_months: 60, upfront_cash: "26580.00", payments_total: "0.00",
    balloon_paid: "0.00", running_costs_total: "0.00", resale_credit: "0.00", settlement_debit: "0.00",
    deposit_refund: "0.00", gross: "338397.80", amount_back: "134655.29", net: "203742.51", net_per_month: "3395.71",
    ...overrides,
  };
}

const PATHWAY_TCO: PathwayTco = {
  hire_purchase: entry(), gfv_retain: entry(), gfv_return: entry({ horizon_months: 60 }), subscription: entry(),
};

function makeReport(overrides: Partial<TcoReport> = {}): TcoReport {
  return {
    vehicle_id: 5, tenure_months: 60, mileage_band: "standard", downpayment: "26580.00", hp_monthly: "4545.18",
    model_degraded: false, degraded_reason: null,
    monthly_forecast: [
      { month: 0, predicted_resale_value: "265800.00", hp_outstanding_balance: "239220.00" },
      { month: 1, predicted_resale_value: "262000.00", hp_outstanding_balance: "235000.00" },
    ],
    tco_gross: "338397.80", tco_net: "203742.51", pathway_tco: PATHWAY_TCO,
    road_tax_annual: "379.00", insurance_annual: "4784.40", maintenance_annual: "2658.00",
    negative_equity_crossover_month: null, negative_equity_shortfall_amount: null, resale_value_explanation: null,
    risk_radar: {}, radar_unavailable: {}, cumulative_cash_flow: [], contract_checklist: null, risk_alerts: [],
    ...overrides,
  };
}

describe("TcoReportView resale notes", () => {
  it("shows the views note once, at the top of the pathway cost table, as sent", () => {
    render(<TcoReportView report={makeReport({ resale_views_note: VIEWS_NOTE })} />);

    const note = screen.getAllByText(VIEWS_NOTE);
    expect(note).toHaveLength(1);
    const card = screen.getByRole("heading", { name: "Total cost by pathway" }).parentElement!;
    expect(card).toContainElement(note[0]);
  });

  // Redesign UI-3: the forecast note is folded into "About this forecast" in the chart
  // card (it sat directly under the intro line); still in the page, one click away.
  it("shows the forecast note once, in the chart card's 'About this forecast', as sent", () => {
    render(<TcoReportView report={makeReport({ resale_forecast_note: FORECAST_NOTE })} />);

    const note = screen.getAllByText(FORECAST_NOTE);
    expect(note).toHaveLength(1);
    const details = note[0].closest("details")!;
    expect(details.querySelector("summary")).toHaveTextContent("About this forecast");
    const card = screen.getByRole("heading", { name: "Remaining loan vs. predicted car value" }).parentElement!;
    expect(card).toContainElement(details);
  });

  it("shows both notes together, each in its own place", () => {
    render(<TcoReportView report={makeReport({ resale_views_note: VIEWS_NOTE, resale_forecast_note: FORECAST_NOTE })} />);

    expect(screen.getAllByText(VIEWS_NOTE)).toHaveLength(1);
    expect(screen.getAllByText(FORECAST_NOTE)).toHaveLength(1);
  });

  it("renders an older snapshot (neither key at all) exactly as before, without crashing", () => {
    const old = makeReport();
    expect("resale_views_note" in old).toBe(false);
    expect("resale_forecast_note" in old).toBe(false);

    const { container } = render(<TcoReportView report={old} />);

    expect(screen.queryByText(/lender's GFV residual for this car is/)).not.toBeInTheDocument();
    expect(screen.queryByText(/machine-learning estimate for this car's brand tier/)).not.toBeInTheDocument();
    expect(screen.getByText("Remaining loan vs. predicted car value")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Total cost by pathway" })).toBeInTheDocument();
    expect(container.textContent).not.toContain("undefined");
  });

  it.each([null, "", undefined])("renders nothing for a %j note (the fallback curve / no GFV)", (value) => {
    render(<TcoReportView report={makeReport({ resale_views_note: value, resale_forecast_note: value })} />);

    expect(screen.queryByText(/lender's GFV residual/)).not.toBeInTheDocument();
    expect(screen.queryByText(/machine-learning estimate/)).not.toBeInTheDocument();
  });

  // Run 3 fix batch 6: the mileage-cap note, only when the server says a cap applied.
  const CAP_NOTE = "The forecast is capped at the mileage the model has seen.";

  // Redesign UI-3: the cap note stays visible (never folded), right under the chart's
  // intro line (it followed the forecast note, which is now in an expander).
  it("shows the mileage-cap note once, visible under the chart's intro line, as sent", () => {
    render(<TcoReportView report={makeReport({ resale_forecast_note: FORECAST_NOTE, forecast_cap_note: CAP_NOTE })} />);

    const note = screen.getAllByText(CAP_NOTE);
    expect(note).toHaveLength(1);
    expect(note[0].closest("details")).toBeNull();
    expect(note[0].previousElementSibling).toHaveTextContent(
      "Predicted resale value against the outstanding Hire Purchase balance over the 60-month term.",
    );
  });

  it.each([null, undefined])("shows no mileage-cap note for %j (no cap applied, or an older snapshot)", (value) => {
    const report = makeReport({ resale_forecast_note: FORECAST_NOTE, forecast_cap_note: value });
    if (value === undefined) delete report.forecast_cap_note;

    const { container } = render(<TcoReportView report={report} />);

    expect(screen.queryByText(/capped at the mileage/)).not.toBeInTheDocument();
    expect(container.textContent).not.toContain("undefined");
  });

  it("works without the pathway table too (a snapshot from before it existed)", () => {
    render(<TcoReportView report={makeReport({ pathway_tco: undefined, resale_views_note: VIEWS_NOTE })} />);

    // There is no table to carry the sentence, and nothing breaks.
    expect(screen.queryByText(VIEWS_NOTE)).not.toBeInTheDocument();
    expect(screen.getByText("60-month total cost of ownership")).toBeInTheDocument();
  });
});
