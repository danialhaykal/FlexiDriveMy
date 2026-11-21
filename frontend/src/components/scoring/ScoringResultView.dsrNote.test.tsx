import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ScoringResultView } from "./ScoringResultView";
import type { ScoringResult } from "../../types/scoring";

// Run 3 fix batch 5 (F-23, F-24): the server's "just over the limit" note sits
// under the DSR figure, and the server-built rationale is shown as-is.

const NOTE = "Just over your 50% limit (50.00003%).";

function result(dsrNote?: string | null): ScoringResult {
  return {
    vehicle_id: 5,
    weights: { upfront_cash_preservation: "0.3333", maintenance_protection: "0.3333", ownership_equity: "0.3333" },
    monthly_income: "14514.75",
    max_dsr_percent: "50.00",
    pathways: {
      subscription: { monthly_instalment: "5701.93", upfront_cash: "11403.86", dsr_percent: "39.28", exceeds_dsr: false,
        dsr_note: null, suitability_score: "65.24" },
      hire_purchase: { monthly_instalment: "7257.38", upfront_cash: "26780.00", dsr_percent: "50.00", exceeds_dsr: true,
        ...(dsrNote === undefined ? {} : { dsr_note: dsrNote }), suitability_score: "0.00" },
    },
    ranking: ["subscription", "hire_purchase"],
    recommended_pathway: "subscription",
    unavailable: {},
    rationale: "Subscription best matches your priorities, scoring 65.24% suitability - reflecting that you rated your priorities equally.",
  } as ScoringResult;
}

describe("ScoringResultView DSR note and rationale", () => {
  it("shows the server's note under the 50.00% DSR that exceeds a 50% limit", () => {
    render(<ScoringResultView result={result(NOTE)} />);

    expect(screen.getByText("50.00%")).toBeInTheDocument();
    expect(screen.getByText("Exceeds DSR")).toBeInTheDocument();
    expect(screen.getByText(NOTE)).toBeInTheDocument();
  });

  it("shows nothing extra without a note (null, or an older snapshot without the field)", () => {
    const { unmount } = render(<ScoringResultView result={result(null)} />);
    expect(screen.queryByText(/Just over/)).not.toBeInTheDocument();
    unmount();

    render(<ScoringResultView result={result(undefined)} />);
    expect(screen.queryByText(/Just over/)).not.toBeInTheDocument();
  });

  it("shows the tie rationale exactly as the server wrote it", () => {
    render(<ScoringResultView result={result(NOTE)} />);

    expect(screen.getByText(/reflecting that you rated your priorities equally\.$/)).toBeInTheDocument();
  });
});
