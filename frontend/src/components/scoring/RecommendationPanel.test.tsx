import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { RecommendationPanel } from "./RecommendationPanel";
import { fetchScoring } from "../../api/scoring";
import type { ScoringResult } from "../../types/scoring";

vi.mock("../../api/scoring", () => ({
  fetchScoring: vi.fn(),
}));

const mockedFetchScoring = vi.mocked(fetchScoring);

function makeScoringResult(overrides: Partial<ScoringResult> = {}): ScoringResult {
  return {
    vehicle_id: 1,
    weights: {
      upfront_cash_preservation: "0.3333",
      maintenance_protection: "0.3333",
      ownership_equity: "0.3333",
    },
    monthly_income: "8000.00",
    max_dsr_percent: "60.00",
    pathways: {
      hire_purchase: {
        monthly_instalment: "2725.00",
        upfront_cash: "10000.00",
        dsr_percent: "34.06",
        exceeds_dsr: false,
        suitability_score: "60.00",
      },
      gfv_leasing: {
        monthly_instalment: "1336.11",
        upfront_cash: "10000.00",
        dsr_percent: "16.70",
        exceeds_dsr: false,
        suitability_score: "70.00",
      },
      subscription: {
        monthly_instalment: "1250.00",
        upfront_cash: "0.00",
        dsr_percent: "15.63",
        exceeds_dsr: false,
        suitability_score: "80.00",
      },
    },
    ranking: ["subscription", "gfv_leasing", "hire_purchase"],
    recommended_pathway: "subscription",
    rationale: "Subscription best matches your priorities.",
    unavailable: {},
    ...overrides,
  };
}

// QA audit M6: these inputs are controlled props in the real app (lifted
// to ComparisonPage so they survive a tab unmount) - this wrapper is the
// test's own stand-in "parent" state.
function ControlledRecommendationPanel() {
  const [upfrontCashPreservation, setUpfrontCashPreservation] = useState<number | null>(null);
  const [maintenanceProtection, setMaintenanceProtection] = useState<number | null>(null);
  const [ownershipEquity, setOwnershipEquity] = useState<number | null>(null);
  const [monthlyIncome, setMonthlyIncome] = useState("");
  const [maxDsrPercent, setMaxDsrPercent] = useState("");

  return (
    <RecommendationPanel
      vehicleId={1}
      tenureMonths={36}
      mileageBand="standard"
      downpayment="10000.00"
      downpaymentError={null}
      upfrontCashPreservation={upfrontCashPreservation}
      onUpfrontCashPreservationChange={setUpfrontCashPreservation}
      maintenanceProtection={maintenanceProtection}
      onMaintenanceProtectionChange={setMaintenanceProtection}
      ownershipEquity={ownershipEquity}
      onOwnershipEquityChange={setOwnershipEquity}
      monthlyIncome={monthlyIncome}
      onMonthlyIncomeChange={setMonthlyIncome}
      maxDsrPercent={maxDsrPercent}
      onMaxDsrPercentChange={setMaxDsrPercent}
    />
  );
}

function renderPanel() {
  return render(<ControlledRecommendationPanel />);
}

const QUIZ_INCOMPLETE_MESSAGE = "Please rate all three priorities to receive a recommendation.";

describe("RecommendationPanel", () => {
  beforeEach(() => {
    mockedFetchScoring.mockReset();
  });

  it("shows a 'Not yet rated' badge on every unanswered slider", () => {
    renderPanel();

    expect(screen.getAllByText("Not yet rated")).toHaveLength(3);
  });

  // --- Audit batch 6 (F2): what is shown is exactly what is sent --------------

  it("shows NO number on an unrated slider, and sends nothing", () => {
    renderPanel();

    // No pre-selected 3: every slider is unrated, with no numeric value shown.
    for (const label of ["Upfront cash preservation", "Maintenance protection", "Ownership equity"]) {
      expect(screen.getByLabelText(label)).toHaveAttribute("aria-valuetext", "Not yet rated");
    }
    expect(screen.queryByText("3")).not.toBeInTheDocument();
    for (const n of ["1", "2", "3", "4", "5"]) expect(screen.queryByText(n)).not.toBeInTheDocument();
    expect(mockedFetchScoring).not.toHaveBeenCalled();
    // The recommendation stays withheld, with the UC007 message from the backend rule.
    expect(screen.getByText(QUIZ_INCOMPLETE_MESSAGE)).toBeInTheDocument();
  });

  it("tells the buyer how to rate, and names which priorities are still unrated", () => {
    renderPanel();

    expect(
      screen.getByText(
        "Drag each slider to rate how much it matters to you (1 = not important, 5 = very important).",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Still to rate: Upfront cash preservation, Maintenance protection, Ownership equity.",
      ),
    ).toBeInTheDocument();
  });

  it("updates the 'still to rate' line as one, two, then all three sliders are rated", () => {
    renderPanel();

    fireEvent.change(screen.getByLabelText("Maintenance protection"), { target: { value: "4" } });
    expect(
      screen.getByText("Still to rate: Upfront cash preservation, Ownership equity."),
    ).toBeInTheDocument();
    expect(screen.getAllByText("Not yet rated")).toHaveLength(2);

    fireEvent.change(screen.getByLabelText("Upfront cash preservation"), { target: { value: "2" } });
    expect(screen.getByText("Still to rate: Ownership equity.")).toBeInTheDocument();
    expect(screen.getAllByText("Not yet rated")).toHaveLength(1);

    fireEvent.change(screen.getByLabelText("Ownership equity"), { target: { value: "5" } });
    expect(screen.queryByText(/Still to rate/)).not.toBeInTheDocument();
    expect(screen.queryAllByText("Not yet rated")).toHaveLength(0);
  });

  it("sends exactly the ratings it displays", async () => {
    mockedFetchScoring.mockResolvedValue(makeScoringResult());
    renderPanel();

    fireEvent.change(screen.getByLabelText("Upfront cash preservation"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Maintenance protection"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Ownership equity"), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("Monthly income (gross, RM)"), { target: { value: "8000" } });
    fireEvent.change(screen.getByLabelText("Max DSR limit (%)"), { target: { value: "60" } });

    // the numbers on screen...
    expect(screen.getByText("5")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
    // ...are the numbers in the request
    await screen.findByText("Subscription best matches your priorities.");
    expect(mockedFetchScoring).toHaveBeenLastCalledWith(
      expect.objectContaining({ upfrontCashPreservation: 5, maintenanceProtection: 2, ownershipEquity: 4 }),
    );
  });

  it("does not treat tabbing through the sliders as rating them", () => {
    renderPanel();

    fireEvent.keyUp(screen.getByLabelText("Upfront cash preservation"), { key: "Tab" });
    fireEvent.keyUp(screen.getByLabelText("Maintenance protection"), { key: "Tab" });

    expect(screen.getAllByText("Not yet rated")).toHaveLength(3);
  });

  // --- QA audit M5: the literal bug, not a vague UX complaint ----------

  it("registers a slider as answered when the user's FIRST interaction ends exactly on the value already displayed", async () => {
    // Every slider defaults its display to 3 while unanswered
    // (RecommendationPanel's `?? 3`) - a real <input type="range"> fires
    // no change/input event at all if the committed value equals what's
    // already shown, so picking 3 as the very first interaction used to
    // leave the criterion permanently "unanswered". Asserting on the
    // slider's own displayed value would pass even on the broken version
    // (it already showed "3") - the real assertion is the quiz-complete
    // state transition below.
    renderPanel();
    expect(screen.getByText(QUIZ_INCOMPLETE_MESSAGE)).toBeInTheDocument();

    fireEvent.pointerUp(screen.getByLabelText("Upfront cash preservation"));
    fireEvent.pointerUp(screen.getByLabelText("Maintenance protection"));
    fireEvent.pointerUp(screen.getByLabelText("Ownership equity"));

    // All three now "answered" (each still showing 3) - the quiz-
    // incomplete message must be gone, replaced by the next alternate-flow
    // prompt (income/DSR), proving the state genuinely transitioned.
    expect(screen.queryByText(QUIZ_INCOMPLETE_MESSAGE)).not.toBeInTheDocument();
    expect(
      screen.getByText("Enter your monthly income and maximum DSR limit to see a recommendation."),
    ).toBeInTheDocument();
    expect(screen.queryAllByText("Not yet rated")).toHaveLength(0);
  });

  // --- QA audit M13 -----------------------------------------------------

  it("surfaces a DRF field error for monthly_income, not the generic fallback", async () => {
    mockedFetchScoring.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 400, data: { monthly_income: ["Must be a positive amount."] } },
    });
    renderPanel();

    fireEvent.change(screen.getByLabelText("Upfront cash preservation"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Maintenance protection"), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("Ownership equity"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Monthly income (gross, RM)"), { target: { value: "-100" } });
    fireEvent.change(screen.getByLabelText("Max DSR limit (%)"), { target: { value: "60" } });

    expect(await screen.findByText("Must be a positive amount.")).toBeInTheDocument();
  });

  it("surfaces a DRF field error for max_dsr_percent, not the generic fallback", async () => {
    mockedFetchScoring.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 400, data: { max_dsr_percent: ["Must be between 0 and 100."] } },
    });
    renderPanel();

    fireEvent.change(screen.getByLabelText("Upfront cash preservation"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Maintenance protection"), { target: { value: "4" } });
    fireEvent.change(screen.getByLabelText("Ownership equity"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Monthly income (gross, RM)"), { target: { value: "8000" } });
    fireEvent.change(screen.getByLabelText("Max DSR limit (%)"), { target: { value: "150" } });

    expect(await screen.findByText("Must be between 0 and 100.")).toBeInTheDocument();
  });

  it("fetches a recommendation once the quiz and income/DSR are all filled in", async () => {
    mockedFetchScoring.mockResolvedValueOnce(makeScoringResult());
    renderPanel();

    fireEvent.change(screen.getByLabelText("Upfront cash preservation"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Maintenance protection"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Ownership equity"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Monthly income (gross, RM)"), { target: { value: "8000" } });
    fireEvent.change(screen.getByLabelText("Max DSR limit (%)"), { target: { value: "60" } });

    expect(await screen.findByText("Subscription best matches your priorities.")).toBeInTheDocument();
    expect(mockedFetchScoring).toHaveBeenCalledWith(
      expect.objectContaining({
        upfrontCashPreservation: 5,
        maintenanceProtection: 2,
        ownershipEquity: 1,
        monthlyIncome: "8000",
        maxDsrPercent: "60",
      }),
    );
  });
});
