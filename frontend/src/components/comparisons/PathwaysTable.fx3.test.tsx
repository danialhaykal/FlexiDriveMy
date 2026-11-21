import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { PathwaysTable, gfvMaxDownpaymentLine } from "./PathwaysTable";
import type { ComparisonResult } from "../../types/comparisons";

// FX-3 (item 1): GFV's downpayment limit as a lead line, from the API's own gfv_max_downpayment field only.

const EXCEEDS = "Your downpayment exceeds the amount financed under GFV (maximum RM 129,106.38 for this term).";

function makeComparison(overrides: Partial<ComparisonResult> = {}): ComparisonResult {
  return {
    vehicle_id: 5, tenure_months: 36, mileage_band: "standard", downpayment: "26780.00",
    hire_purchase: {
      monthly_instalment: "7257.38", upfront_cash: "26780.00", total_contract_outlay: "288045.68",
      interest_rate_percent: "2.8000", effective_rate_percent: "5.3118",
    },
    gfv_leasing: {
      monthly_instalment: "3404.78", upfront_cash: "26780.00", total_contract_outlay: "288045.68",
      balloon_payment: "138693.62", residual_value_ratio: "0.5179", effective_rate_percent: "3.9000",
    },
    subscription: null,
    unavailable: { subscription: "Not offered." },
    gfv_max_downpayment: "129106.38",
    ...overrides,
  };
}

const LINE = "Maximum downpayment for GFV at this term: RM 129,106.38";

describe("GFV maximum downpayment lead line", () => {
  it("is built from the field and only the field", () => {
    expect(gfvMaxDownpaymentLine("129106.38")).toBe(LINE);
    expect(gfvMaxDownpaymentLine(null)).toBeNull();
    expect(gfvMaxDownpaymentLine(undefined)).toBeNull();
  });

  it("shows on the GFV card while GFV is offered", () => {
    render(<PathwaysTable comparison={makeComparison()} />);

    const card = screen.getByRole("article", { name: "GFV Leasing" });
    expect(within(card).getByText(LINE)).toBeInTheDocument();
  });

  it("leads the unavailable card above the unchanged reason when the downpayment is too high", () => {
    render(
      <PathwaysTable
        comparison={makeComparison({ downpayment: "200000.00", gfv_leasing: null, unavailable: { gfv_leasing: EXCEEDS } })}
      />,
    );

    const card = screen.getByRole("article", { name: "GFV Leasing" });
    const lead = within(card).getByText(LINE);
    const reason = within(card).getByText(EXCEEDS);
    expect(lead.compareDocumentPosition(reason) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("is absent when the API sends null (GFV not offered for the term)", () => {
    render(
      <PathwaysTable
        comparison={makeComparison({
          tenure_months: 72, gfv_leasing: null, gfv_max_downpayment: null,
          unavailable: { gfv_leasing: "GFV leasing isn't offered for 72 months." },
        })}
      />,
    );

    expect(screen.queryByText(/Maximum downpayment for GFV/)).not.toBeInTheDocument();
  });

  it("is absent on an older saved snapshot without the field", () => {
    const old = makeComparison();
    delete old.gfv_max_downpayment;
    render(<PathwaysTable comparison={old} />);

    expect(screen.queryByText(/Maximum downpayment for GFV/)).not.toBeInTheDocument();
    expect(screen.getByRole("article", { name: "GFV Leasing" })).toBeInTheDocument();
  });
});
