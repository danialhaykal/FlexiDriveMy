import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { PATHWAY_TCO_NOTE, PathwayTcoTable } from "./PathwayTcoTable";
import type { PathwayTco, PathwayTcoEntry } from "../../types/depreciation";

// The API's own figures (BMW 320i, 26,580 down, standard band, NCD 0) - the
// table only labels and formats them.
function entry(overrides: Partial<PathwayTcoEntry>): PathwayTcoEntry {
  return {
    available: true,
    unavailable_reason: null,
    horizon_months: 60,
    upfront_cash: "26580.00",
    payments_total: "0.00",
    balloon_paid: "0.00",
    running_costs_total: "0.00",
    resale_credit: "0.00",
    settlement_debit: "0.00",
    deposit_refund: "0.00",
    gross: "0.00",
    amount_back: "0.00",
    net: "0.00",
    net_per_month: "0.00",
    ...overrides,
  };
}

const UNAVAILABLE: Partial<PathwayTcoEntry> = {
  available: false, upfront_cash: null, payments_total: null, balloon_paid: null, running_costs_total: null,
  resale_credit: null, settlement_debit: null, deposit_refund: null, gross: null, amount_back: null, net: null,
  net_per_month: null,
};

const AT_36: PathwayTco = {
  hire_purchase: entry({ gross: "325001.48", amount_back: "93030.00", net: "231971.48", net_per_month: "3866.19" }),
  gfv_retain: entry({
    gross: "325001.48", amount_back: "93030.00", net: "231971.48", net_per_month: "3866.19",
    gfv_guarantee_value: "0.00",
  }),
  gfv_return: entry({
    horizon_months: 36, gross: "176458.68", amount_back: "0.00", net: "176458.68", net_per_month: "4901.63",
    gfv_guarantee_value: "0.00",
  }),
  subscription: entry({
    horizon_months: 36, gross: "216673.34", amount_back: "11403.86", net: "205269.48", net_per_month: "5701.93",
  }),
};

function row(label: string) {
  const cell = screen.getByText(label);
  const tr = cell.closest("tr");
  if (!tr) throw new Error(`row ${label} not found`);
  return within(tr);
}

describe("PathwayTcoTable", () => {
  it("shows the four pathways with the API's figures and their horizons", () => {
    render(<PathwayTcoTable pathwayTco={AT_36} />);

    for (const header of ["Pathway", "What you pay", "What you get back", "Net cost", "Net cost per month of use"]) {
      expect(screen.getByRole("columnheader", { name: header })).toBeInTheDocument();
    }
    const hp = row("Hire Purchase");
    expect(hp.getByText("over 60 months, you keep the car")).toBeInTheDocument();
    expect(hp.getByText("RM 325,001.48")).toBeInTheDocument();
    expect(hp.getByText("RM 93,030.00")).toBeInTheDocument();
    expect(hp.getByText("RM 231,971.48")).toBeInTheDocument();
    expect(hp.getByText("RM 3,866.19")).toBeInTheDocument();

    const ret = row("GFV - hand the car back");
    expect(ret.getByText("over 36 months, car returned")).toBeInTheDocument();
    expect(ret.getByText("RM 4,901.63")).toBeInTheDocument();
    expect(row("GFV - pay the balloon and keep the car").getByText("over 60 months, you keep the car")).toBeInTheDocument();

    const sub = row("Subscription");
    expect(sub.getByText("RM 11,403.86")).toBeInTheDocument(); // the deposit back
    expect(sub.getByText("RM 5,701.93")).toBeInTheDocument();
    expect(screen.getByText(PATHWAY_TCO_NOTE)).toBeInTheDocument();
  });

  it("shows an unavailable pathway with its reason instead of figures", () => {
    const at84: PathwayTco = {
      ...AT_36,
      gfv_retain: entry({
        ...UNAVAILABLE,
        unavailable_reason: "GFV leasing isn't offered for 84 months - it is offered for 12 to 60 months in 12-month steps.",
      }),
      subscription: entry({
        ...UNAVAILABLE, horizon_months: 84, unavailable_reason: "Subscription plans run for 12, 24 or 36 months.",
      }),
    };

    render(<PathwayTcoTable pathwayTco={at84} />);

    expect(
      row("Subscription").getByText("Not available: Subscription plans run for 12, 24 or 36 months."),
    ).toBeInTheDocument();
    expect(row("GFV - pay the balloon and keep the car").getByText(/Not available: GFV leasing isn't offered/)).toBeInTheDocument();
    expect(row("Subscription").queryByText(/^RM /)).not.toBeInTheDocument();
    // Run 1 fix batch 5: only the reason - no horizon the buyer can't have.
    expect(row("Subscription").queryByText(/over 84 months/)).not.toBeInTheDocument();
    expect(row("GFV - pay the balloon and keep the car").queryByText(/you keep the car/)).not.toBeInTheDocument();
    expect(row("Hire Purchase").getByText("RM 231,971.48")).toBeInTheDocument();
  });
});
