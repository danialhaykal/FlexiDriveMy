import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { SANDBOX_DEBOUNCE_MS, TotalLossSandboxPanel } from "./TotalLossSandboxPanel";
import { fetchTotalLossSandbox } from "../../api/depreciation";
import type { TotalLossSandboxResult } from "../../types/totalLossSandbox";

vi.mock("../../api/depreciation", () => ({
  fetchTotalLossSandbox: vi.fn(),
}));

const mockedFetchTotalLossSandbox = vi.mocked(fetchTotalLossSandbox);

// The exact example response from Sprint 12's own hand-checked reference
// case: price=100000, downpayment=10000, tenure=36, residual=50%, month
// 18 -> resale (straight-line fallback) 82000.00, HP balance 45000.00
// (net +37000.00), GFV balance 70000.00 (net +12000.00) - both surpluses.
function makeSandboxResult(overrides: Partial<TotalLossSandboxResult> = {}): TotalLossSandboxResult {
  return {
    vehicle_id: 1,
    tenure_months: 36,
    mileage_band: "standard",
    downpayment: "10000.00",
    loss_month: 0,
    excess_amount: "0.00",
    model_degraded: true,
    degraded_reason: "ML forecast service unavailable. Showing standardized linear depreciation model.",
    resale_value_is_plateaued: false,
    hire_purchase: {
      insurance_payout: "82000.00",
      outstanding_balance: "45000.00",
      net_position: "37000.00",
      has_ownership_exposure: true,
    },
    gfv_leasing: {
      insurance_payout: "82000.00",
      outstanding_balance: "70000.00",
      net_position: "12000.00",
      has_ownership_exposure: true,
    },
    subscription: {
      // QA audit L8: null - no ownership stake, no insurance claim.
      insurance_payout: null,
      outstanding_balance: null,
      net_position: null,
      has_ownership_exposure: false,
    },
    unavailable: {},
    ...overrides,
  };
}

function renderPanel() {
  return render(
    <TotalLossSandboxPanel
      vehicleId={1}
      tenureMonths={36}
      mileageBand="standard"
      downpayment="10000.00"
      downpaymentError={null}
    />,
  );
}

describe("TotalLossSandboxPanel", () => {
  beforeEach(() => {
    mockedFetchTotalLossSandbox.mockReset();
  });

  it("fetches immediately on mount with the default month (QA audit L8: tenure/2, not 0) and zero excess", async () => {
    mockedFetchTotalLossSandbox.mockResolvedValueOnce(makeSandboxResult());

    renderPanel();

    expect(await screen.findByText("RM 45,000.00")).toBeInTheDocument(); // HP balance, loaded
    expect(mockedFetchTotalLossSandbox).toHaveBeenCalledWith(
      expect.objectContaining({
        vehicle: 1,
        tenureMonths: 36,
        mileageBand: "standard",
        downpayment: "10000.00",
        lossMonth: 18, // tenureMonths (36) / 2
        excessAmount: "0",
      }),
    );
  });

  it("shows the always-visible illustrative disclaimer regardless of load state", () => {
    mockedFetchTotalLossSandbox.mockReturnValueOnce(new Promise(() => {})); // never resolves

    renderPanel();

    expect(
      screen.getByText(/illustrative only/i, { exact: false }),
    ).toBeInTheDocument();
  });

  it("renders each pathway's figures, colors net position by sign, and marks Subscription not applicable", async () => {
    mockedFetchTotalLossSandbox.mockResolvedValueOnce(makeSandboxResult());

    renderPanel();

    expect(await screen.findByText("RM 45,000.00")).toBeInTheDocument(); // HP balance
    expect(screen.getByText("RM 70,000.00")).toBeInTheDocument(); // GFV balance
    expect(screen.getByText("+RM 37,000.00")).toBeInTheDocument(); // HP surplus
    expect(screen.getByText("+RM 12,000.00")).toBeInTheDocument(); // GFV surplus

    expect(screen.getAllByText("Ownership exposure")).toHaveLength(2); // HP + GFV
    expect(screen.getByText("No ownership exposure")).toBeInTheDocument(); // Subscription
    // QA audit L8: Subscription's insurance_payout is now also null, so
    // this text now appears twice (payout + balance), not once.
    expect(screen.getAllByText("Not applicable - no ownership stake")).toHaveLength(2);
    expect(screen.getByText("Not applicable")).toBeInTheDocument(); // net position

    // Degraded ML forecast notice is shown, same message as the TCO tab's own.
    expect(
      screen.getByText("ML forecast service unavailable. Showing standardized linear depreciation model."),
    ).toBeInTheDocument();
  });

  it("labels the balance as the estimated amount to settle, keeping the illustrative note", async () => {
    mockedFetchTotalLossSandbox.mockResolvedValueOnce(makeSandboxResult());

    renderPanel();

    expect(await screen.findAllByText("Amount to settle (estimate)")).toHaveLength(3); // one per pathway card
    expect(screen.queryByText("Outstanding balance")).not.toBeInTheDocument();
    expect(screen.getByText(/illustrative only/i, { exact: false })).toBeInTheDocument();
  });

  it("shows a shortfall in danger styling when net position is negative", async () => {
    mockedFetchTotalLossSandbox.mockResolvedValueOnce(
      makeSandboxResult({
        gfv_leasing: {
          insurance_payout: "62000.00",
          outstanding_balance: "70000.00",
          net_position: "-8000.00",
          has_ownership_exposure: true,
        },
      }),
    );

    renderPanel();

    const shortfall = await screen.findByText("-RM 8,000.00");
    expect(shortfall).toHaveClass("text-danger-700");
  });

  it("re-fetches with the updated month when the slider changes", async () => {
    mockedFetchTotalLossSandbox.mockResolvedValueOnce(makeSandboxResult());
    renderPanel();
    await screen.findByText("RM 45,000.00");
    expect(mockedFetchTotalLossSandbox).toHaveBeenCalledTimes(1);

    const atMonth24 = makeSandboxResult({ loss_month: 24 });
    if (atMonth24.hire_purchase) atMonth24.hire_purchase.outstanding_balance = "30000.00";
    mockedFetchTotalLossSandbox.mockResolvedValueOnce(atMonth24);
    fireEvent.change(screen.getByLabelText("Month of loss"), { target: { value: "24" } });

    expect(await screen.findByText("RM 30,000.00")).toBeInTheDocument();
    expect(mockedFetchTotalLossSandbox).toHaveBeenCalledTimes(2);
    expect(mockedFetchTotalLossSandbox).toHaveBeenLastCalledWith(
      expect.objectContaining({ lossMonth: 24 }),
    );
  });

  // --- Run 1 fix batch 5 (X3): month 0 is not a choice ---------------------------

  it("starts the month slider at 1, so month 0 is never sent", async () => {
    mockedFetchTotalLossSandbox.mockResolvedValue(makeSandboxResult());
    renderPanel();
    await screen.findByText("RM 45,000.00");

    const slider = screen.getByLabelText("Month of loss");
    expect(slider).toHaveAttribute("min", "1");
    fireEvent.change(slider, { target: { value: "0" } }); // what a stale value or a bad input might try

    for (const [params] of mockedFetchTotalLossSandbox.mock.calls) {
      expect(params.lossMonth).toBeGreaterThanOrEqual(1);
    }
  });

  it("shows the API's month message if it ever refuses one", async () => {
    mockedFetchTotalLossSandbox.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 400, data: { loss_month: ["Choose a month from 1 to 36."] } },
    });
    renderPanel();

    expect(await screen.findByText("Choose a month from 1 to 36.")).toBeInTheDocument();
  });

  it("shows the loading skeleton while the request is in flight", async () => {
    mockedFetchTotalLossSandbox.mockReturnValueOnce(new Promise(() => {})); // never resolves

    renderPanel();

    expect(await screen.findAllByRole("status", { name: "Loading" })).not.toHaveLength(0);
  });

  it("shows the parsed detail message verbatim on a 400 response", async () => {
    mockedFetchTotalLossSandbox.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 400,
        data: { detail: "No active GFV residual ratio configured for brand 'Honda' at 36 months / 'standard' mileage band." },
      },
    });

    renderPanel();

    expect(
      await screen.findByText(
        "No active GFV residual ratio configured for brand 'Honda' at 36 months / 'standard' mileage band.",
      ),
    ).toBeInTheDocument();
  });

  // Run 3 fix batch 4 (F-19): a pathway the comparison does not offer comes back null with
  // the comparison's own reason; its card says "Not available" and prints that reason as-is.
  it("shows 'Not available' with the server's reason for a GFV that is not offered, and keeps Hire Purchase", async () => {
    const reason = "Your downpayment exceeds the amount financed under GFV (maximum RM 61,594.00 for this term).";
    mockedFetchTotalLossSandbox.mockResolvedValueOnce(
      makeSandboxResult({ gfv_leasing: null, unavailable: { gfv_leasing: reason } }),
    );

    renderPanel();

    expect(await screen.findByText(reason)).toBeInTheDocument();
    expect(screen.getByText("Not available")).toBeInTheDocument();
    expect(screen.queryByText("RM 70,000.00")).not.toBeInTheDocument(); // no GFV figures
    expect(screen.getByText("RM 45,000.00")).toBeInTheDocument(); // Hire Purchase unchanged
    expect(screen.getAllByText("Ownership exposure")).toHaveLength(1);
  });

  it("shows both Hire Purchase and GFV as not available, with their reasons, when neither is offered", async () => {
    const reason = "Hire Purchase and GFV aren't available for this car yet because its financing rate hasn't been set up.";
    mockedFetchTotalLossSandbox.mockResolvedValueOnce(
      makeSandboxResult({ hire_purchase: null, gfv_leasing: null, unavailable: { hire_purchase: reason, gfv_leasing: reason } }),
    );

    renderPanel();

    expect(await screen.findAllByText(reason)).toHaveLength(2);
    expect(screen.getAllByText("Not available")).toHaveLength(2);
    expect(screen.getByText("No ownership exposure")).toBeInTheDocument(); // Subscription card unchanged
  });
  // FX-1 (X1): written off in the balloon month the balloon is still owed. The panel shows the API's figures as they
  // come: GFV's amount to settle is the balloon and its net is payout - balloon; Hire Purchase is fully repaid (0.00).
  it("shows the balloon as GFV's amount to settle when the loss month is the last month", async () => {
    mockedFetchTotalLossSandbox.mockResolvedValueOnce(
      makeSandboxResult({
        loss_month: 36,
        hire_purchase: { insurance_payout: "183998.38", outstanding_balance: "0.00", net_position: "183998.38", has_ownership_exposure: true },
        gfv_leasing: { insurance_payout: "183998.38", outstanding_balance: "138693.62", net_position: "45304.76", has_ownership_exposure: true },
      }),
    );

    renderPanel();

    const gfvCard = (await screen.findByRole("heading", { name: "GFV Leasing" })).parentElement!.parentElement!;
    expect(within(gfvCard).getByText("RM 138,693.62")).toBeInTheDocument();
    expect(within(gfvCard).getByText("+RM 45,304.76")).toBeInTheDocument();
    expect(within(gfvCard).queryByText("RM 0.00")).not.toBeInTheDocument();
    const hpCard = screen.getByRole("heading", { name: "Hire Purchase" }).parentElement!.parentElement!;
    expect(within(hpCard).getByText("RM 0.00")).toBeInTheDocument();
    expect(within(hpCard).getByText("+RM 183,998.38")).toBeInTheDocument();
  });
});

// FX-2 (item 12, R4-P7-01): one request after the month slider rests, not one per step; the label follows each step.
describe("TotalLossSandboxPanel debounce", () => {
  beforeEach(() => {
    mockedFetchTotalLossSandbox.mockReset();
  });

  it("asks once for the month the slider rests on, while 'Month N' follows every step", async () => {
    mockedFetchTotalLossSandbox.mockResolvedValue(makeSandboxResult());
    renderPanel();
    await screen.findByText("RM 45,000.00"); // the first month (18) loads at once
    expect(mockedFetchTotalLossSandbox).toHaveBeenCalledTimes(1);

    const slider = screen.getByRole("slider", { name: "Month of loss" });
    for (const month of ["19", "20", "21", "22"]) fireEvent.change(slider, { target: { value: month } });
    expect(screen.getByText("Month 22")).toBeInTheDocument(); // at once

    await vi.waitFor(() => expect(mockedFetchTotalLossSandbox).toHaveBeenCalledTimes(2));
    expect(mockedFetchTotalLossSandbox.mock.calls[1][0]).toEqual(expect.objectContaining({ lossMonth: 22 }));
    await new Promise((resolve) => setTimeout(resolve, SANDBOX_DEBOUNCE_MS + 150));
    expect(mockedFetchTotalLossSandbox).toHaveBeenCalledTimes(2);
    expect(SANDBOX_DEBOUNCE_MS).toBe(250);
  });

  it("never shows the previous month's figures under the new month's label while it waits", async () => {
    mockedFetchTotalLossSandbox.mockResolvedValue(makeSandboxResult());
    renderPanel();
    await screen.findByText("RM 45,000.00");

    fireEvent.change(screen.getByRole("slider", { name: "Month of loss" }), { target: { value: "30" } });

    expect(screen.getByText("Month 30")).toBeInTheDocument();
    expect(screen.queryByText("RM 45,000.00")).not.toBeInTheDocument(); // loading, not month 18's figures
    expect(await screen.findByText("RM 45,000.00")).toBeInTheDocument(); // month 30's answer (same mock) arrives
  });
});
