import { describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { GFV_FORMULA_TEXT, ISLAMIC_NOTE, PathwaysTable, RATES_NOTE } from "./PathwaysTable";
import type { ComparisonResult } from "../../types/comparisons";
import { API_MILEAGE_BANDS, includedMileageNote } from "../../test/mileageBandsFixture";

// Audit batch 3: the dealer's rate is a FLAT rate and says so; the effective
// (reducing-balance) rate the API derives sits beside it. Everything shown
// is exactly what the API returned - nothing is computed here.

function makeComparison(overrides: Partial<ComparisonResult> = {}): ComparisonResult {
  return {
    vehicle_id: 1,
    tenure_months: 48,
    mileage_band: "standard",
    downpayment: "26580.00",
    hire_purchase: {
      monthly_instalment: "5541.93",
      upfront_cash: "26580.00",
      total_contract_outlay: "292592.64",
      interest_rate_percent: "2.8000",
      effective_rate_percent: "5.3027",
    },
    gfv_leasing: {
      monthly_instalment: "3216.18",
      upfront_cash: "26580.00",
      total_contract_outlay: "292592.64",
      balloon_payment: "111636.00",
      residual_value_ratio: "0.4200",
      effective_rate_percent: "3.7556",
    },
    subscription: {
      monthly_instalment: "6500.00",
      upfront_cash: "0.00",
      total_contract_outlay: "312000.00",
      net_cost_after_bundled_benefits: "5400.00",
    },
    unavailable: {},
    ...overrides,
  };
}

describe("PathwaysTable rate labels", () => {
  it("labels the Hire Purchase rate as flat and shows the effective rate beside it", () => {
    render(<PathwaysTable comparison={makeComparison()} />);

    expect(screen.getByText("2.80% flat p.a.")).toBeInTheDocument();
    expect(screen.getByText("≈ 5.30% effective p.a.")).toBeInTheDocument();
    // The bare, unlabelled "2.80% p.a." that looked like a bank's effective rate is gone.
    expect(screen.queryByText("2.80% p.a.")).not.toBeInTheDocument();
  });

  it("keeps the GFV residual badge and adds its effective rate", () => {
    render(<PathwaysTable comparison={makeComparison()} />);

    expect(screen.getByText("42.00% residual")).toBeInTheDocument();
    expect(screen.getByText("≈ 3.76% effective p.a.")).toBeInTheDocument();
  });

  it("shows the flat-vs-effective explanation under the table", () => {
    render(<PathwaysTable comparison={makeComparison()} />);

    expect(screen.getByText(RATES_NOTE)).toBeInTheDocument();
    expect(RATES_NOTE).toBe(
      "Rates are shown as flat rates, the way dealers quote them. The effective rate is the reducing-balance equivalent a bank would disclose. Under the Hire-Purchase (Amendment) Act 2026, lenders move to effective-rate disclosure by 31 March 2027, so your final offer may be quoted that way.",
    );
    expect(screen.queryByText(ISLAMIC_NOTE)).not.toBeInTheDocument();
  });

  it("renders an old saved snapshot without the effective rate: the flat label only, no error", () => {
    const old = makeComparison();
    delete old.hire_purchase!.effective_rate_percent;
    delete old.gfv_leasing!.effective_rate_percent;

    render(<PathwaysTable comparison={old} />);

    expect(screen.getByText("2.80% flat p.a.")).toBeInTheDocument();
    expect(screen.queryByText(/effective p\.a\./)).not.toBeInTheDocument();
    expect(screen.getByText("RM 5,541.93")).toBeInTheDocument();
  });

  it("shows no effective badge when the API returned null", () => {
    const comparison = makeComparison();
    comparison.hire_purchase!.effective_rate_percent = null;

    render(<PathwaysTable comparison={comparison} />);

    expect(screen.queryByText(/≈ .* effective p\.a\./, { selector: "span" })).toBeInTheDocument(); // GFV's
    expect(screen.getAllByText(/effective p\.a\./)).toHaveLength(1);
  });

  it("omits the rates note when neither rate-bearing pathway is available", () => {
    render(
      <PathwaysTable
        comparison={makeComparison({
          hire_purchase: null,
          gfv_leasing: null,
          unavailable: { hire_purchase: "No rate.", gfv_leasing: "No rate." },
        })}
      />,
    );

    expect(screen.queryByText(RATES_NOTE)).not.toBeInTheDocument();
  });
});

describe("PathwaysTable residual basis (audit batch 4)", () => {
  const BASIS = "Estimate: 42% baseline for 48 months / standard mileage, +6 pts Toyota, 0 pts petrol";

  it("shows where the GFV residual came from, as a muted line under the residual badge", () => {
    const comparison = makeComparison();
    comparison.gfv_leasing!.residual_basis = BASIS;

    render(<PathwaysTable comparison={comparison} />);

    expect(screen.getByText(BASIS)).toBeInTheDocument();
    expect(screen.getByText("42.00% residual")).toBeInTheDocument();
  });

  it("shows an admin override's basis as given", () => {
    const comparison = makeComparison();
    comparison.gfv_leasing!.residual_basis = "Admin override for BMW, 48 months, standard mileage";

    render(<PathwaysTable comparison={comparison} />);

    expect(screen.getByText("Admin override for BMW, 48 months, standard mileage")).toBeInTheDocument();
  });

  it("renders a frozen older snapshot with no basis: the badge only, no empty line, no error", () => {
    const { container } = render(<PathwaysTable comparison={makeComparison()} />);

    expect(screen.getByText("42.00% residual")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/Estimate:|Admin override/);
  });
});

describe("PathwaysTable Subscription estimate (audit batch 5)", () => {
  const BASIS =
    "Estimate: depreciation RM 3,691.67 + funding RM 747.56 + road tax, insurance and maintenance RM 651.78, plus 12% margin";
  const MILEAGE =
    `${includedMileageNote("standard")} Kilometres above that are billed per km (RM 0.50/km under the default contract rule).`;

  function withSubscription(extra: Record<string, unknown>) {
    const comparison = makeComparison();
    comparison.subscription = { ...comparison.subscription!, upfront_cash: "11403.86", ...extra } as never;
    return comparison;
  }

  it("shows an Estimate badge, the basis, the mileage note and the refundable-deposit note", () => {
    render(
      <PathwaysTable
        comparison={withSubscription({
          fee_source: "estimate", fee_basis: BASIS, refundable_deposit: "11403.86",
          included_km_per_year: API_MILEAGE_BANDS[1].included_km_per_year, mileage_note: MILEAGE,
        })}
      />,
    );

    expect(screen.getByText("Estimate")).toBeInTheDocument();
    expect(screen.getByText(BASIS)).toBeInTheDocument();
    expect(screen.getByText(MILEAGE)).toBeInTheDocument();
    expect(
      screen.getByText(
        "Refundable deposit RM 11,403.86 is included in upfront cash and returned at the end of the term.",
      ),
    ).toBeInTheDocument();
    // the existing offset line is kept
    expect(screen.getByText(/Effective cost after bundled insurance\/road tax\/maintenance/)).toBeInTheDocument();
  });

  it("shows a Provider quote badge for an admin-keyed quote", () => {
    render(
      <PathwaysTable
        comparison={withSubscription({ fee_source: "quote", fee_basis: "Provider quote - fixed fee" })}
      />,
    );

    expect(screen.getByText("Provider quote")).toBeInTheDocument();
    expect(screen.getByText("Provider quote - fixed fee")).toBeInTheDocument();
    expect(screen.queryByText("Estimate")).not.toBeInTheDocument();
  });

  it("shows the server's message in the Not available row when Subscription does not run for the tenure", () => {
    render(
      <PathwaysTable
        comparison={makeComparison({
          subscription: null,
          unavailable: { subscription: "Subscription plans run for 12, 24 or 36 months." },
        })}
      />,
    );

    expect(screen.getByText("Subscription plans run for 12, 24 or 36 months.")).toBeInTheDocument();
    expect(screen.getAllByText("Not available")).toHaveLength(1);
    expect(screen.queryByText(/Refundable deposit/)).not.toBeInTheDocument();
  });

  it("renders a frozen older snapshot with none of the new keys exactly as before", () => {
    const { container } = render(<PathwaysTable comparison={makeComparison()} />);

    expect(screen.getByText("Subscription")).toBeInTheDocument();
    expect(screen.getByText("RM 6,500.00")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/Estimate|Provider quote|Refundable deposit|Includes up to/);
  });
});

describe("PathwaysTable Islamic-financing wording", () => {
  it("says 'Profit rate' and adds the indicative note, with every figure unchanged", () => {
    render(<PathwaysTable comparison={makeComparison()} prefersIslamicFinancing />);

    expect(screen.getByText("Profit rate 2.80% flat p.a.")).toBeInTheDocument();
    expect(screen.getByText("≈ 5.30% effective p.a.")).toBeInTheDocument();
    // FX-2 (item 7): the note is on the HP card itself too, under the "Profit rate" badge (was one copy).
    expect(screen.getAllByText(ISLAMIC_NOTE)).toHaveLength(2);
    expect(within(screen.getByRole("article", { name: "Hire Purchase" })).getByText(ISLAMIC_NOTE)).toBeInTheDocument();
    expect(ISLAMIC_NOTE).toBe("Indicative: Islamic financing is not priced separately in this app.");
    expect(screen.getByText("RM 5,541.93")).toBeInTheDocument();
    expect(screen.getByText("RM 3,216.18")).toBeInTheDocument();
    expect(screen.getByText(RATES_NOTE)).toBeInTheDocument();
  });

  it("never calls interest an 'interest rate' once the preference is on, nor claims Shariah compliance", () => {
    const { container } = render(<PathwaysTable comparison={makeComparison()} prefersIslamicFinancing />);

    expect(container.textContent).not.toMatch(/interest rate/i);
    expect(container.textContent).not.toMatch(/shariah/i);
    expect(container.textContent).not.toMatch(/compliant/i);
  });

  it("is a wording change only: the same figures render with and without the preference", () => {
    const { container: plain } = render(<PathwaysTable comparison={makeComparison()} />);
    const plainFigures = plain.textContent!.match(/RM [\d,]+\.\d{2}/g);
    const { container: islamic } = render(<PathwaysTable comparison={makeComparison()} prefersIslamicFinancing />);

    expect(islamic.textContent!.match(/RM [\d,]+\.\d{2}/g)).toEqual(plainFigures);
  });

  // --- Run 1 fix batch 4: GFV explained -------------------------------------------

  it("shows the server's end-of-term choice and same-total sentences on the GFV card", () => {
    const comparison = makeComparison();
    comparison.gfv_leasing!.end_of_term_note =
      "At month 36 you choose: pay the balloon of RM 200,000.00 and keep the car, hand the car back (within the mileage and condition terms), or refinance the balloon.";
    comparison.gfv_leasing!.same_total_note =
      "Same total as Hire Purchase because both use the same flat rate on the same amount. GFV's benefits are the lower monthly payment and the guaranteed buy-back value.";

    render(<PathwaysTable comparison={comparison} />);

    expect(screen.getByText(comparison.gfv_leasing!.end_of_term_note)).toBeInTheDocument();
    expect(screen.getByText(comparison.gfv_leasing!.same_total_note)).toBeInTheDocument();
  });

  it("renders an older snapshot's GFV card without those sentences", () => {
    render(<PathwaysTable comparison={makeComparison()} />);

    expect(screen.queryByText(/you choose: pay the balloon/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Same total as Hire Purchase/)).not.toBeInTheDocument();
  });

  // --- Run 2 fix batch 2 (E3): what the GFV residual is ---------------------------------

  const RESALE_NOTE =
    "This residual is the lender's conservative guaranteed buy-back value. The expected market value (shown on the TCO tab) is usually higher.";

  it("shows the server's resale sentence under the other GFV notes, exactly as sent", () => {
    const comparison = makeComparison();
    comparison.gfv_leasing!.end_of_term_note = "At month 48 you choose: pay the balloon.";
    comparison.gfv_leasing!.same_total_note = "Same total as Hire Purchase.";
    comparison.gfv_leasing!.resale_note = RESALE_NOTE;

    render(<PathwaysTable comparison={comparison} />);

    const note = screen.getByText(RESALE_NOTE);
    expect(note).toBeInTheDocument();
    // UI-3: in "What happens at the end of GFV", right after the end-of-term choice (it
    // followed the same-total sentence, which now has its own expander).
    expect(note.previousElementSibling).toHaveTextContent("At month 48 you choose: pay the balloon.");
  });

  it("renders an older snapshot (no resale_note) exactly as before, without crashing", () => {
    const comparison = makeComparison();
    expect(comparison.gfv_leasing!.resale_note).toBeUndefined();

    render(<PathwaysTable comparison={comparison} />);

    expect(screen.queryByText(/conservative guaranteed buy-back value/)).not.toBeInTheDocument();
    expect(screen.getByText("42.00% residual")).toBeInTheDocument();
  });

  it("shows no resale sentence when the server sends null (the car's curve isn't a machine-learning forecast)", () => {
    const comparison = makeComparison();
    comparison.gfv_leasing!.same_total_note = "Same total as Hire Purchase.";
    comparison.gfv_leasing!.resale_note = null;

    const { container } = render(<PathwaysTable comparison={comparison} />);

    expect(screen.getByText("Same total as Hire Purchase.")).toBeInTheDocument();
    expect(screen.queryByText(/conservative guaranteed buy-back value/)).not.toBeInTheDocument();
    expect(container.textContent).not.toContain("null");
  });

  // --- Run 1 fix batch 3: the subscription offset nets the owner's insurance ----

  it("says the offset is before No-Claim Discount when the API applied none", () => {
    render(<PathwaysTable comparison={makeComparison({ ncd_percent: "0.00" })} />);

    expect(
      screen.getByText("Insurance shown before No-Claim Discount. Add your NCD in Financial Profile."),
    ).toBeInTheDocument();
  });

  it.each([
    ["the buyer has an NCD", { ncd_percent: "55.00" }],
    ["a snapshot saved before NCD existed", {}],
  ])("shows no NCD note when %s", (_label, overrides) => {
    render(<PathwaysTable comparison={makeComparison(overrides)} />);

    expect(screen.queryByText(/before No-Claim Discount/)).not.toBeInTheDocument();
    // The offset itself is the API's figure, unchanged.
    expect(screen.getByText("RM 5,400.00")).toBeInTheDocument();
  });
});

// --- Redesign UI-3: cards, Recommended only from the scoring API, the prompt -----------------

describe("PathwaysTable cards (redesign UI-3)", () => {
  it("shows Recommended on exactly the card the scoring API recommended, and on none otherwise", () => {
    const { rerender } = render(<PathwaysTable comparison={makeComparison()} />);
    expect(screen.queryByText("Recommended")).not.toBeInTheDocument();

    rerender(<PathwaysTable comparison={makeComparison()} recommendedPathway="gfv_leasing" />);
    expect(screen.getAllByText("Recommended")).toHaveLength(1);
    expect(within(screen.getByRole("article", { name: "GFV Leasing" })).getByText("Recommended")).toBeInTheDocument();

    rerender(<PathwaysTable comparison={makeComparison()} recommendedPathway={null} />);
    expect(screen.queryByText("Recommended")).not.toBeInTheDocument();
  });

  it("keeps the rate and estimate badges visible and folds the long sentences into expanders", () => {
    const comparison = makeComparison();
    comparison.subscription = { ...comparison.subscription!, fee_source: "estimate", fee_basis: "Estimate: depreciation ..." };
    comparison.gfv_leasing!.residual_basis = "Estimate: 42% baseline for 48 months / standard mileage";

    render(<PathwaysTable comparison={comparison} />);

    for (const badge of ["2.80% flat p.a.", "≈ 5.30% effective p.a.", "Estimate"]) {
      expect(screen.getByText(badge).closest("details")).toBeNull();
    }
    expect(screen.getByText(RATES_NOTE).closest("details")?.querySelector("summary")).toHaveTextContent("Flat vs effective rate");
    expect(screen.getByText(/Hire-Purchase \(Amendment\) Act 2026/)).toBeInTheDocument();
    expect(screen.getByText("Estimate: 42% baseline for 48 months / standard mileage").closest("details")).not.toBeNull();
    expect(screen.getByText("Estimate: depreciation ...").closest("details")).not.toBeNull();
  });

  it("shows the GFV balloon as a fact with the tenure, and the end-of-term sentences in their expander", () => {
    const comparison = makeComparison();
    comparison.gfv_leasing!.end_of_term_note = "At month 48 you choose: pay the balloon.";

    render(<PathwaysTable comparison={comparison} />);
    const gfv = within(screen.getByRole("article", { name: "GFV Leasing" }));

    expect(gfv.getByText("Balloon at month 48").nextElementSibling).toHaveTextContent("RM 111,636.00");
    expect(screen.getByText("At month 48 you choose: pay the balloon.").closest("details")?.querySelector("summary")).toHaveTextContent(
      "What happens at the end of GFV",
    );
  });

  it("offers Rate your priorities when there is no recommendation yet, and calls back on click", async () => {
    const onRatePriorities = vi.fn();
    const { rerender } = render(<PathwaysTable comparison={makeComparison()} onRatePriorities={onRatePriorities} />);

    expect(screen.getByText("Not sure which suits you?")).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: "Rate your priorities" }));
    expect(onRatePriorities).toHaveBeenCalledTimes(1);

    rerender(<PathwaysTable comparison={makeComparison()} onRatePriorities={onRatePriorities} recommendedPathway="subscription" />);
    expect(screen.queryByText("Not sure which suits you?")).not.toBeInTheDocument();
  });

  it("shows no prompt where there is no AI tab to open (the saved page)", () => {
    render(<PathwaysTable comparison={makeComparison()} />);

    expect(screen.queryByRole("button", { name: "Rate your priorities" })).not.toBeInTheDocument();
  });
});

// FX-2 (item 6): the GFV "How is this calculated?" starts with the monthly formula in words, then the server's basis.
describe("PathwaysTable GFV formula", () => {
  it("shows the formula first and keeps the server's residual basis", () => {
    const comparison = makeComparison();
    comparison.gfv_leasing!.residual_basis = "Estimate: 43.79% baseline for 48 months / standard mileage";
    render(<PathwaysTable comparison={comparison} />);

    const gfv = screen.getByRole("article", { name: "GFV Leasing" });
    const formula = within(gfv).getByText(GFV_FORMULA_TEXT);
    expect(GFV_FORMULA_TEXT).toBe(
      "Monthly = (amount financed − balloon) ÷ months + interest on the amount financed (flat rate) ÷ 12",
    );
    const paragraphs = Array.from(formula.parentElement!.querySelectorAll("p"));
    expect(paragraphs[0]).toBe(formula);
    expect(paragraphs[1]).toHaveTextContent("Estimate: 43.79% baseline for 48 months / standard mileage"); // unchanged, after it
  });
});
