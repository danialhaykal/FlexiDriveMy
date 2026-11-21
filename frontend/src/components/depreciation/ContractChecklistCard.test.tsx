import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ContractChecklistCard } from "./ContractChecklistCard";

describe("ContractChecklistCard", () => {
  it("renders the three fields when a checklist is configured", () => {
    render(
      <ContractChecklistCard
        checklist={{
          excess_mileage_charge_per_km: "0.50",
          early_termination_fee: "5000.00",
          wear_tear_tolerance_description: "Normal wear and tear accepted.",
        }}
      />,
    );

    expect(screen.getByText("RM 0.50 / km (estimate)") /* FX-2 (item 7): was "RM 0.50 / km" */).toBeInTheDocument();
    expect(screen.getByText("RM 5,000.00")).toBeInTheDocument();
    expect(screen.getByText("Normal wear and tear accepted.")).toBeInTheDocument();
  });

  // --- Run 1 (B7): two different early exits ------------------------------------

  const current = {
    excess_mileage_charge_per_km: "0.50",
    early_settlement: {
      method: "reducing_balance" as const,
      after_12_months: "196280.44",
      at_half_term: "127476.28",
      half_term_month: 30,
      penalty: "none" as const,
    },
    subscription_early_return_months: "3.00",
    subscription_early_return_fee: "17105.79",
    early_termination_months: "3.00",
    early_termination_months_source: "default" as const,
    rule_source: "default" as const,
    wear_tear_tolerance_description: "Normal wear and tear accepted.",
  };

  it("shows HP early settlement (no penalty, amounts to settle) and the subscription early-return fee as two rows", () => {
    render(<ContractChecklistCard checklist={current} />);

    expect(screen.getByText("Settling a Hire Purchase loan early")).toBeInTheDocument();
    expect(
      screen.getByText(
        "No penalty under the reducing-balance method. Estimated amount to settle after 12 months: RM 196,280.44; at month 30: RM 127,476.28.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Returning a subscription car early")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Up to 3 months of the subscription fee (about RM 17,105.79), or the fees left, whichever is lower.",
      ),
    ).toBeInTheDocument();
    // the old HP "months of instalments" wording is gone from a current report
    expect(screen.queryByText(/of instalments/)).not.toBeInTheDocument();
    expect(screen.queryByText("Early termination")).not.toBeInTheDocument();
  });

  it("omits the 12-month sentence when the loan is 12 months or shorter", () => {
    render(
      <ContractChecklistCard
        checklist={{
          ...current,
          early_settlement: { ...current.early_settlement, after_12_months: null, at_half_term: "120000.00", half_term_month: 6 },
        }}
      />,
    );

    expect(
      screen.getByText("No penalty under the reducing-balance method. Estimated amount to settle at month 6: RM 120,000.00."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/after 12 months/)).not.toBeInTheDocument();
  });

  it("states just the months when Subscription isn't available for this tenure (no fee)", () => {
    render(<ContractChecklistCard checklist={{ ...current, subscription_early_return_fee: null }} />);

    expect(screen.getByText("Up to 3 months of the subscription fee.")).toBeInTheDocument();
    expect(screen.queryByText(/about RM/)).not.toBeInTheDocument();
  });

  it("keeps a snapshot saved before run 1 exactly as it was (its old instalment-based row)", () => {
    render(
      <ContractChecklistCard
        checklist={{
          excess_mileage_charge_per_km: "0.50",
          early_termination_months: "3.00",
          early_termination_amount: "13635.54",
          early_termination_months_source: "default",
          rule_source: "default",
          wear_tear_tolerance_description: "Normal wear and tear accepted.",
        }}
      />,
    );

    expect(screen.getByText("Early termination")).toBeInTheDocument();
    expect(screen.getByText("Up to 3 months of instalments (about RM 13,635.54)")).toBeInTheDocument();
    expect(screen.queryByText("Settling a Hire Purchase loan early")).not.toBeInTheDocument();
  });

  // --- Audit batch 4: early termination = N months of the instalment ---------

  const defaultRule = {
    excess_mileage_charge_per_km: "0.50",
    early_termination_months: "3.00",
    early_termination_amount: "8175.00",
    rule_source: "default" as const,
    early_termination_months_source: "default" as const,
    wear_tear_tolerance_description: "Normal wear and tear accepted.",
  };

  it("shows early termination as months of instalments with the server's amount, and says the default rule applied", () => {
    render(<ContractChecklistCard checklist={defaultRule} />);

    expect(screen.getByText("Up to 3 months of instalments (about RM 8,175.00)")).toBeInTheDocument();
    expect(screen.getByText("RM 0.50 / km (estimate)") /* FX-2 (item 7): was "RM 0.50 / km" */).toBeInTheDocument();
    expect(screen.getByText(/Terms from the default contract rule/)).toBeInTheDocument();
    expect(screen.queryByText("Early termination fee")).not.toBeInTheDocument();
  });

  it("says a brand's own rule applied, and when its months were inherited from the default", () => {
    const { rerender } = render(
      <ContractChecklistCard
        checklist={{ ...defaultRule, rule_source: "brand", early_termination_months: "6.00", early_termination_amount: "16350.00", early_termination_months_source: "brand" }}
      />,
    );
    expect(screen.getByText("Up to 6 months of instalments (about RM 16,350.00)")).toBeInTheDocument();
    expect(screen.getByText("Terms from this brand's own contract rule.")).toBeInTheDocument();

    rerender(<ContractChecklistCard checklist={{ ...defaultRule, rule_source: "brand" }} />);
    expect(
      screen.getByText("Terms from this brand's own contract rule (early-termination months from the default rule)."),
    ).toBeInTheDocument();
  });

  it("shows a fractional or single month sensibly", () => {
    const { rerender } = render(
      <ContractChecklistCard checklist={{ ...defaultRule, early_termination_months: "2.50", early_termination_amount: "2645.83" }} />,
    );
    expect(screen.getByText("Up to 2.5 months of instalments (about RM 2,645.83)")).toBeInTheDocument();

    rerender(
      <ContractChecklistCard checklist={{ ...defaultRule, early_termination_months: "1.00", early_termination_amount: "1000.00" }} />,
    );
    expect(screen.getByText("Up to 1 month of instalments (about RM 1,000.00)")).toBeInTheDocument();
    // a whole number of ten months is not mangled by the trailing-zero trim
    rerender(<ContractChecklistCard checklist={{ ...defaultRule, early_termination_months: "10", early_termination_amount: null }} />);
    expect(screen.getByText("Up to 10 months of instalments")).toBeInTheDocument();
  });

  it("says that wear and tear is a checklist item, not a cost", () => {
    render(<ContractChecklistCard checklist={defaultRule} />);

    expect(
      screen.getByText(/Wear and tear is a checklist item only, not a cost in the totals/),
    ).toBeInTheDocument();
    expect(screen.getByText(/already priced into the car's resale value/)).toBeInTheDocument();
  });

  it("renders a frozen pre-batch-4 scenario: the stored fee as saved, no source line, no crash", () => {
    render(
      <ContractChecklistCard
        checklist={{
          excess_mileage_charge_per_km: "0.50",
          early_termination_fee: "5000.00",
          wear_tear_tolerance_description: "Old terms.",
        }}
      />,
    );

    expect(screen.getByText("RM 5,000.00")).toBeInTheDocument();
    expect(screen.queryByText(/Terms from/)).not.toBeInTheDocument();
    expect(screen.queryByText(/months of instalments/)).not.toBeInTheDocument();
  });

  it("shows an empty-state note instead of hiding the section when null", () => {
    render(<ContractChecklistCard checklist={null} />);

    expect(screen.getByText("Contract terms not yet configured for this brand")).toBeInTheDocument();
  });

  // Live-walkthrough finding: a scenario saved before Batch 6C added
  // contract_checklist has no such key at all in its stored payload -
  // `checklist` is genuinely `undefined`, not `null`, and the old
  // `checklist === null` check previously fell through to
  // `checklist.excess_mileage_charge_per_km`, throwing.
  it("shows the same empty-state note (not a crash) when checklist is undefined", () => {
    render(<ContractChecklistCard checklist={undefined} />);

    expect(screen.getByText("Contract terms not yet configured for this brand")).toBeInTheDocument();
  });
});
