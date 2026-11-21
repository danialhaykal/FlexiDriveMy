import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { DsrSimulatorPanel } from "./DsrSimulatorPanel";
import { fetchDsrSimulator } from "../../api/scoring";
import type { DsrSimulatorResult } from "../../types/dsrSimulator";

vi.mock("../../api/scoring", () => ({
  fetchDsrSimulator: vi.fn(),
}));

const mockedFetchDsrSimulator = vi.mocked(fetchDsrSimulator);

// The exact example response from the DSR Simulator's API contract
// (Sprint 11's own hand-checked reference case: HP=2725.00/27.25%,
// GFV=1336.11/13.36%, Subscription=1250.00/12.50%, income=10000.00).
function makeDsrResult(overrides: Partial<DsrSimulatorResult> = {}): DsrSimulatorResult {
  return {
    vehicle_id: 1,
    monthly_income: "10000.00",
    max_dsr_percent: "30.00",
    pathways: {
      hire_purchase: {
        monthly_instalment: "2725.00",
        existing_monthly_commitments: "0.00",
        dsr_percent: "27.25",
        exceeds_dsr: false,
        is_ccris_reportable: true,
      },
      gfv_leasing: {
        monthly_instalment: "1336.11",
        existing_monthly_commitments: "0.00",
        dsr_percent: "13.36",
        exceeds_dsr: false,
        is_ccris_reportable: true,
      },
      subscription: {
        monthly_instalment: "1250.00",
        existing_monthly_commitments: "0.00",
        dsr_percent: "12.50",
        exceeds_dsr: false,
        is_ccris_reportable: false,
      },
    },
    unavailable: {},
    ...overrides,
  };
}

// QA audit M6: monthlyIncome/maxDsrPercent/existingMonthlyCommitments
// are now controlled props (lifted to ComparisonPage in the real app, so
// they survive a tab unmount) - this wrapper is the test's own stand-in
// "parent" state, letting every existing fireEvent.change interaction
// below keep working unchanged.
function ControlledDsrSimulatorPanel() {
  const [monthlyIncome, setMonthlyIncome] = useState("");
  const [maxDsrPercent, setMaxDsrPercent] = useState("");
  const [existingMonthlyCommitments, setExistingMonthlyCommitments] = useState("");

  return (
    <DsrSimulatorPanel
      vehicleId={1}
      tenureMonths={36}
      mileageBand="standard"
      downpayment="10000.00"
      downpaymentError={null}
      monthlyIncome={monthlyIncome}
      onMonthlyIncomeChange={setMonthlyIncome}
      maxDsrPercent={maxDsrPercent}
      onMaxDsrPercentChange={setMaxDsrPercent}
      existingMonthlyCommitments={existingMonthlyCommitments}
      onExistingMonthlyCommitmentsChange={setExistingMonthlyCommitments}
    />
  );
}

function renderPanel() {
  return render(<ControlledDsrSimulatorPanel />);
}

describe("DsrSimulatorPanel", () => {
  beforeEach(() => {
    mockedFetchDsrSimulator.mockReset();
  });

  it("does not fetch until monthly income and max DSR limit are both filled in", async () => {
    renderPanel();

    expect(
      screen.getByText(
        "Enter your monthly income and maximum DSR limit to see your affordability simulation.",
      ),
    ).toBeInTheDocument();
    expect(mockedFetchDsrSimulator).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("Monthly income (gross, RM)"), { target: { value: "10000" } });
    expect(mockedFetchDsrSimulator).not.toHaveBeenCalled();

    mockedFetchDsrSimulator.mockResolvedValueOnce(makeDsrResult());
    fireEvent.change(screen.getByLabelText("Max DSR limit (%)"), { target: { value: "30" } });

    expect(await screen.findByText("RM 2,725.00")).toBeInTheDocument();
    expect(mockedFetchDsrSimulator).toHaveBeenCalledTimes(1);
  });

  it("renders each pathway's figures and CCRIS-reportable labels once loaded", async () => {
    mockedFetchDsrSimulator.mockResolvedValueOnce(makeDsrResult());

    renderPanel();
    fireEvent.change(screen.getByLabelText("Monthly income (gross, RM)"), { target: { value: "10000" } });
    fireEvent.change(screen.getByLabelText("Max DSR limit (%)"), { target: { value: "30" } });

    expect(await screen.findByText("RM 2,725.00")).toBeInTheDocument(); // HP monthly
    expect(screen.getByText("RM 1,336.11")).toBeInTheDocument(); // GFV monthly
    expect(screen.getByText("RM 1,250.00")).toBeInTheDocument(); // Subscription monthly
    expect(screen.getByText("27.25%")).toBeInTheDocument();
    expect(screen.getByText("13.36%")).toBeInTheDocument();
    expect(screen.getByText("12.50%")).toBeInTheDocument();

    // HP and GFV are credit agreements reported to CCRIS; Subscription isn't.
    expect(screen.getAllByText("CCRIS-reportable")).toHaveLength(2);
    expect(screen.getByText("Off-CCRIS")).toBeInTheDocument();
    expect(screen.queryByText("Exceeds your DSR limit")).not.toBeInTheDocument();

    expect(
      screen.getByText(
        "Based on your self-declared income and commitments - FlexiDriveMy does not connect to CCRIS or any credit bureau.",
      ),
    ).toBeInTheDocument();

    expect(mockedFetchDsrSimulator).toHaveBeenCalledWith(
      expect.objectContaining({
        vehicle: 1,
        tenureMonths: 36,
        mileageBand: "standard",
        downpayment: "10000.00",
        monthlyIncome: "10000",
        maxDsrPercent: "30",
        existingMonthlyCommitments: "0",
      }),
    );
  });

  it("passes existing_monthly_commitments through once entered, and shows the exceeds-DSR badge", async () => {
    // Two calls fire: the first once income+maxDsr are both filled in, the
    // second after existingMonthlyCommitments is then entered - only the
    // second response is what this test actually checks.
    mockedFetchDsrSimulator.mockResolvedValueOnce(makeDsrResult());
    mockedFetchDsrSimulator.mockResolvedValueOnce(
      makeDsrResult({
        pathways: {
          ...makeDsrResult().pathways,
          hire_purchase: {
            monthly_instalment: "2725.00",
            existing_monthly_commitments: "1000.00",
            dsr_percent: "37.25",
            exceeds_dsr: true,
            is_ccris_reportable: true,
          },
        },
      }),
    );

    renderPanel();
    fireEvent.change(screen.getByLabelText("Monthly income (gross, RM)"), { target: { value: "10000" } });
    fireEvent.change(screen.getByLabelText("Max DSR limit (%)"), { target: { value: "30" } });
    fireEvent.change(screen.getByLabelText("Existing monthly commitments (RM)"), {
      target: { value: "1000" },
    });

    expect(await screen.findByText("37.25%")).toBeInTheDocument();
    expect(screen.getByText("Exceeds your DSR limit")).toBeInTheDocument();
    expect(mockedFetchDsrSimulator).toHaveBeenLastCalledWith(
      expect.objectContaining({ existingMonthlyCommitments: "1000" }),
    );
  });

  it("shows the loading skeleton while the request is in flight", async () => {
    mockedFetchDsrSimulator.mockReturnValueOnce(new Promise(() => {})); // never resolves

    renderPanel();
    fireEvent.change(screen.getByLabelText("Monthly income (gross, RM)"), { target: { value: "10000" } });
    fireEvent.change(screen.getByLabelText("Max DSR limit (%)"), { target: { value: "30" } });

    expect(await screen.findAllByRole("status", { name: "Loading" })).not.toHaveLength(0);
  });

  // --- QA audit L16 -----------------------------------------------------

  // Redesign UI-3: the amber "Nearing your DSR limit" state was the browser's own 80%-of-
  // the-limit rule, not an API value; the bar's colour now follows ONLY the API's
  // exceeds_dsr. A pathway close to but within the limit reads as within it.
  it("treats a pathway close to (but within) the limit as within it: no 'nearing' badge, the positive bar", async () => {
    mockedFetchDsrSimulator.mockResolvedValueOnce(
      makeDsrResult({
        max_dsr_percent: "30.00",
        pathways: {
          ...makeDsrResult().pathways,
          hire_purchase: {
            monthly_instalment: "2725.00",
            existing_monthly_commitments: "0.00",
            dsr_percent: "27.00", // 90% of the 30% limit - "nearing", not exceeding
            exceeds_dsr: false,
            is_ccris_reportable: true,
          },
        },
      }),
    );
    renderPanel();
    fireEvent.change(screen.getByLabelText("Monthly income (gross, RM)"), { target: { value: "10000" } });
    fireEvent.change(screen.getByLabelText("Max DSR limit (%)"), { target: { value: "30" } });

    const gauge = await screen.findByRole("progressbar", { name: /hire purchase/i });
    expect(screen.queryByText("Nearing your DSR limit")).not.toBeInTheDocument();
    expect(screen.queryByText("Exceeds your DSR limit")).not.toBeInTheDocument();
    expect(gauge.querySelector(".bg-positive-600")).not.toBeNull();
    expect(gauge.querySelector(".bg-warning-600")).toBeNull();
  });

  // Redesign UI-3: the bar is on a 0-100% of income scale with a marker at the limit
  // (it was scaled to the limit, aria-valuemax 30 / valuenow clamped to 30); the
  // limit is now said in aria-valuetext, and the API's figures are used as sent.
  it("puts the DSR on a 0-100 scale with a marker at the limit, coloured by the API's exceeds_dsr", async () => {
    mockedFetchDsrSimulator.mockResolvedValueOnce(
      makeDsrResult({
        max_dsr_percent: "30.00",
        pathways: {
          ...makeDsrResult().pathways,
          hire_purchase: {
            monthly_instalment: "4000.00",
            existing_monthly_commitments: "0.00",
            dsr_percent: "40.00", // past the 30% limit
            exceeds_dsr: true,
            is_ccris_reportable: true,
          },
        },
      }),
    );
    renderPanel();
    fireEvent.change(screen.getByLabelText("Monthly income (gross, RM)"), { target: { value: "10000" } });
    fireEvent.change(screen.getByLabelText("Max DSR limit (%)"), { target: { value: "30" } });

    const gauge = await screen.findByRole("progressbar", { name: /hire purchase/i });
    expect(gauge).toHaveAttribute("aria-valuemax", "100");
    expect(gauge).toHaveAttribute("aria-valuenow", "40");
    expect(gauge).toHaveAttribute("aria-valuetext", "40.00% of income; your limit is 30.00%");
    const fill = gauge.querySelector(".bg-danger-600") as HTMLElement;
    expect(fill.style.width).toBe("40%"); // the API's "40.00" as sent (the browser normalises "40.00%")
    const marker = gauge.querySelector("[aria-hidden=true]") as HTMLElement;
    expect(marker.style.left).toBe("30%");
  });

  it("never reports an aria-valuenow above 100 for a DSR over 100% of income", async () => {
    mockedFetchDsrSimulator.mockResolvedValueOnce(
      makeDsrResult({
        max_dsr_percent: "60.00",
        pathways: {
          ...makeDsrResult().pathways,
          hire_purchase: {
            monthly_instalment: "12000.00",
            existing_monthly_commitments: "0.00",
            dsr_percent: "120.00",
            exceeds_dsr: true,
            is_ccris_reportable: true,
          },
        },
      }),
    );
    renderPanel();
    fireEvent.change(screen.getByLabelText("Monthly income (gross, RM)"), { target: { value: "10000" } });
    fireEvent.change(screen.getByLabelText("Max DSR limit (%)"), { target: { value: "60" } });

    const gauge = await screen.findByRole("progressbar", { name: /hire purchase/i });
    expect(gauge).toHaveAttribute("aria-valuenow", "100");
  });

  it("shows the parsed detail message verbatim on a 400 response", async () => {
    mockedFetchDsrSimulator.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 400,
        data: { detail: "No active interest rate configured for brand 'Honda'." },
      },
    });

    renderPanel();
    fireEvent.change(screen.getByLabelText("Monthly income (gross, RM)"), { target: { value: "10000" } });
    fireEvent.change(screen.getByLabelText("Max DSR limit (%)"), { target: { value: "30" } });

    expect(
      await screen.findByText("No active interest rate configured for brand 'Honda'."),
    ).toBeInTheDocument();
  });
});

// FX-2 (item 7): the two CCRIS badges are explained one click away.
describe("DsrSimulatorPanel CCRIS explainer", () => {
  it("explains CCRIS-reportable and Off-CCRIS", async () => {
    mockedFetchDsrSimulator.mockResolvedValueOnce(makeDsrResult());

    renderPanel();
    fireEvent.change(screen.getByLabelText("Monthly income (gross, RM)"), { target: { value: "10000" } });
    fireEvent.change(screen.getByLabelText("Max DSR limit (%)"), { target: { value: "30" } });
    await screen.findByText("RM 2,725.00");

    const summary = screen.getByText("What do CCRIS-reportable and Off-CCRIS mean?");
    expect(summary.closest("details")).toHaveTextContent(
      "CCRIS-reportable: the loan appears in your Bank Negara credit report. Off-CCRIS: the subscription is a rental, not a loan.",
    );
  });
});
