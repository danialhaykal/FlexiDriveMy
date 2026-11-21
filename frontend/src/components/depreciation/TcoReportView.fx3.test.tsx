import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { TcoReportView, maintenanceCapSentence } from "./TcoReportView";
import type { TcoReport } from "../../types/depreciation";

// FX-3 (item 1): the running-costs sentence names the yearly maintenance cap from the API's operating_cost_policy.

function makeReport(overrides: Partial<TcoReport> = {}): TcoReport {
  return {
    vehicle_id: 5, tenure_months: 60, mileage_band: "standard", downpayment: "26580.00", hp_monthly: "4545.18",
    model_degraded: false, degraded_reason: null,
    monthly_forecast: [{ month: 0, predicted_resale_value: "265800.00", hp_outstanding_balance: "239220.00" }],
    tco_gross: "338397.80", tco_net: "203742.51",
    road_tax_annual: "379.00", insurance_annual: "4784.40", maintenance_annual: "2658.00",
    negative_equity_crossover_month: null, negative_equity_shortfall_amount: null, resale_value_explanation: null,
    risk_radar: {}, radar_unavailable: {}, cumulative_cash_flow: [], contract_checklist: null, risk_alerts: [],
    ...overrides,
  };
}

const CAPPED =
  "Maintenance is a planning estimate based on the car's price, capped at RM 8,000 a year, and does not change with the mileage band.";
const GENERAL =
  "Maintenance is a planning estimate based on the car's price, with a yearly cap, and does not change with the mileage band.";

describe("maintenance cap sentence", () => {
  it("names the cap the API sent", () => {
    expect(maintenanceCapSentence("8000.00")).toBe(CAPPED);
    expect(maintenanceCapSentence("8500.50")).toContain("capped at RM 8,500.50 a year");
  });

  it("keeps the general wording without a figure", () => {
    expect(maintenanceCapSentence(null)).toBe(GENERAL);
    expect(maintenanceCapSentence(undefined)).toBe(GENERAL);
  });

  it("is shown in How are these estimated? for a live report", () => {
    render(<TcoReportView report={makeReport({ operating_cost_policy: { maintenance_cap_annual: "8000.00" } })} />);

    expect(screen.getByText(CAPPED)).toBeInTheDocument();
  });

  it("an older saved report without the field still renders, with the general wording", () => {
    render(<TcoReportView report={makeReport()} />);

    expect(screen.getByText(GENERAL)).toBeInTheDocument();
  });
});
