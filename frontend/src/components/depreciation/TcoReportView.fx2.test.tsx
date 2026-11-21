import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { TcoReportView } from "./TcoReportView";
import type { PathwayTco, PathwayTcoEntry, TcoReport } from "../../types/depreciation";

// FX-2 (items 6, 7): one horizon wording on the Total cost tab, from the API's own pathway TCO horizon, and the
// maintenance assumption said plainly in "How are these estimated?".

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

describe("TcoReportView FX-2 wording", () => {
  it("titles the summary with the API's horizon and explains a different loan term once", () => {
    render(<TcoReportView report={makeReport({ tenure_months: 36 })} />);

    expect(screen.getByRole("heading", { name: "Total cost over 60 months" })).toBeInTheDocument();
    expect(
      screen.getByText(
        "The loan runs 36 months; total cost is measured over 60 months so every option compares on the same period.",
      ),
    ).toBeInTheDocument();
  });

  it("says nothing extra when the loan runs exactly the horizon", () => {
    render(<TcoReportView report={makeReport({ tenure_months: 60 })} />);

    expect(screen.getByRole("heading", { name: "Total cost over 60 months" })).toBeInTheDocument();
    expect(screen.queryByText(/The loan runs/)).not.toBeInTheDocument();
  });

  it("keeps the old title for a saved snapshot without the pathway TCO", () => {
    render(<TcoReportView report={makeReport({ pathway_tco: undefined })} />);

    expect(screen.getByRole("heading", { name: "60-month total cost of ownership" })).toBeInTheDocument();
  });

  it("says maintenance is a price-based planning estimate that does not change with the mileage band", () => {
    render(<TcoReportView report={makeReport()} />);

    expect(
      screen.getByText(
        "Maintenance is a planning estimate based on the car's price, with a yearly cap, and does not change with the mileage band.",
      ),
    ).toBeInTheDocument();
  });
});
