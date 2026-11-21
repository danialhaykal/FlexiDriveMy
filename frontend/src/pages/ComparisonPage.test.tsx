import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { ComparisonPage } from "./ComparisonPage";
import { fetchVehicleDetail } from "../api/catalog";
import { fetchComparison } from "../api/comparisons";
import { fetchTcoReport } from "../api/depreciation";
import { fetchScoring } from "../api/scoring";
import { exportComparisonPdf } from "../api/exports";
import { fetchFinancialProfile } from "../api/profile";
import { saveScenario } from "../api/scenarios";
import type { Vehicle } from "../types/catalog";
import type { FinancialProfile } from "../types/profile";
import type { ComparisonResult } from "../types/comparisons";
import type { TcoReport } from "../types/depreciation";
import type { ScoringResult } from "../types/scoring";

vi.mock("../api/catalog", () => ({
  fetchVehicleDetail: vi.fn(),
}));
vi.mock("../api/comparisons", () => ({
  fetchComparison: vi.fn(),
}));
vi.mock("../api/depreciation", () => ({
  fetchTcoReport: vi.fn(),
  // FX-1: the If-written-off and Affordability panels are opened by the X3 tests; their figures are not asserted.
  fetchTotalLossSandbox: vi.fn(() => new Promise(() => {})),
}));
vi.mock("../api/scoring", () => ({
  fetchScoring: vi.fn(),
  fetchDsrSimulator: vi.fn(() => new Promise(() => {})),
}));
// Only exportComparisonPdf (the network call) is mocked - parseExportErrorDetail
// keeps its real implementation so the blob/JSON.parse "gotcha" is
// actually exercised by the 504 test below, not assumed away.
vi.mock("../api/exports", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/exports")>();
  return { ...actual, exportComparisonPdf: vi.fn() };
});
vi.mock("../api/scenarios", () => ({
  saveScenario: vi.fn(),
}));
vi.mock("../api/profile", () => ({
  fetchFinancialProfile: vi.fn(),
}));

const mockedFetchVehicleDetail = vi.mocked(fetchVehicleDetail);
const mockedFetchComparison = vi.mocked(fetchComparison);
const mockedFetchTcoReport = vi.mocked(fetchTcoReport);
const mockedFetchScoring = vi.mocked(fetchScoring);
const mockedExportComparisonPdf = vi.mocked(exportComparisonPdf);
const mockedFetchFinancialProfile = vi.mocked(fetchFinancialProfile);
const mockedSaveScenario = vi.mocked(saveScenario);

function makeFinancialProfile(overrides: Partial<FinancialProfile> = {}): FinancialProfile {
  return {
    id: 1,
    monthly_budget: "2500.00",
    preferred_tenure_months: 48,
    annual_mileage_band: "high",
    ownership_preference: "retain",
    shariah_compliant_required: false,
    ncd_percent: "0.00",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function makeVehicle(overrides: Partial<Vehicle> = {}): Vehicle {
  return {
    id: 1,
    brand: 1,
    brand_name: "Honda",
    name: "City",
    trim: "V",
    body_segment: "sedan",
    model_year: 2025,
    msrp: "400000.00",
    min_downpayment: "40000.00",
    engine_capacity_kw: "90.00",
    powertrain: "petrol",
    engine_capacity_cc: 1498,
    spec_complete: true,
    thumbnail_url: "",
    is_active: true,
    ...overrides,
  };
}

// The exact example response from F005's API contract - also doubles as
// the project spec's GFV reference case (P=400000, D=40000, t=36, r=3%, G=50%).
function makeComparisonResult(overrides: Partial<ComparisonResult> = {}): ComparisonResult {
  return {
    vehicle_id: 1,
    tenure_months: 36,
    mileage_band: "standard",
    downpayment: "40000.00",
    hire_purchase: {
      monthly_instalment: "10900.00",
      upfront_cash: "40000.00",
      total_contract_outlay: "432400.00",
      interest_rate_percent: "3.0000",
    },
    gfv_leasing: {
      monthly_instalment: "5344.44",
      upfront_cash: "40000.00",
      // QA audit H9: includes the 200000.00 balloon - true-up of the
      // monthly-payment series (40000 + 5344.4444...*36 = 232400.00,
      // L7) + the balloon = 432400.00.
      total_contract_outlay: "432400.00",
      balloon_payment: "200000.00",
      residual_value_ratio: "0.5000",
    },
    subscription: {
      // QA audit H8: the real, gross fee billed (2000.00 in full) -
      // net_cost_after_bundled_benefits below is the old netted figure,
      // now informational context only.
      monthly_instalment: "2000.00",
      upfront_cash: "0.00",
      total_contract_outlay: "72000.00",
      net_cost_after_bundled_benefits: "1450.00",
    },
    unavailable: {},
    ...overrides,
  };
}

// The exact example response from F006's API contract.
function makeTcoReport(overrides: Partial<TcoReport> = {}): TcoReport {
  return {
    vehicle_id: 1,
    tenure_months: 36,
    mileage_band: "standard",
    downpayment: "40000.00",
    hp_monthly: "10900.00",
    model_degraded: false,
    degraded_reason: null,
    monthly_forecast: [
      { month: 0, predicted_resale_value: "400000.00", hp_outstanding_balance: "360000.00" },
      { month: 1, predicted_resale_value: "397333.33", hp_outstanding_balance: "350000.00" },
    ],
    tco_gross: "612400.00",
    tco_net: "452400.00",
    road_tax_annual: "90.00",
    insurance_annual: "1800.00",
    maintenance_annual: "600.00",
    negative_equity_crossover_month: null,
    negative_equity_shortfall_amount: null,
    resale_value_explanation: null,
    risk_radar: {},
    radar_unavailable: {},
    cumulative_cash_flow: [],
    contract_checklist: null,
    risk_alerts: [],
    ...overrides,
  };
}

// The exact example response from F007's API contract.
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
        monthly_instalment: "10900.00",
        upfront_cash: "40000.00",
        dsr_percent: "136.25",
        exceeds_dsr: true,
        suitability_score: "0.00",
      },
      gfv_leasing: {
        monthly_instalment: "5344.44",
        upfront_cash: "40000.00",
        dsr_percent: "66.81",
        exceeds_dsr: true,
        suitability_score: "0.00",
      },
      subscription: {
        // QA audit H8: the gross fee (consistent with the comparison
        // fixture above) - dsr_percent recomputed to match: 2000/8000 = 25.00%.
        monthly_instalment: "2000.00",
        upfront_cash: "0.00",
        dsr_percent: "25.00",
        exceeds_dsr: false,
        suitability_score: "83.33",
      },
    },
    ranking: ["subscription", "hire_purchase", "gfv_leasing"],
    recommended_pathway: "subscription",
    rationale:
      "Subscription best matches your priorities, scoring 83.33% suitability - reflecting the weight you placed on preserving upfront cash.",
    unavailable: {},
    ...overrides,
  };
}

// Shows the page's current query string, so a test can see what it wrote.
function LocationProbe() {
  return <output data-testid="location-search">{useLocation().search}</output>;
}

function renderPage(query = "") {
  return render(
    <MemoryRouter initialEntries={[`/catalog/1/compare${query}`]}>
      <Routes>
        <Route
          path="/catalog/:id/compare"
          element={
            <>
              <ComparisonPage />
              <LocationProbe />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ComparisonPage", () => {
  beforeEach(() => {
    mockedFetchVehicleDetail.mockReset();
    mockedFetchComparison.mockReset();
    mockedFetchTcoReport.mockReset();
    mockedFetchScoring.mockReset();
    mockedExportComparisonPdf.mockReset();
    mockedSaveScenario.mockReset();
    mockedFetchFinancialProfile.mockReset();
    // Default: no saved baseline - every existing test below keeps
    // relying on the shared 48/"standard" defaults unless it opts
    // into a profile itself.
    mockedFetchFinancialProfile.mockResolvedValue(null);
  });

  describe("Batch 6C: saved financial-profile baseline prefill", () => {
    beforeEach(() => {
      mockedFetchVehicleDetail.mockResolvedValue(makeVehicle());
      mockedFetchComparison.mockResolvedValue(makeComparisonResult());
    });

    // Redesign UI-6c: below sm a "View" select replaces the sideways-scrolling strip.
    it("switches the five views from the 'View' select as well as from the tabs", async () => {
      const user = userEvent.setup();
      renderPage();

      const select = (await screen.findByLabelText("View")) as HTMLSelectElement;
      expect(Array.from(select.options).map((o) => o.textContent)).toEqual([
        "Financing options", "Total cost", "AI recommendation", "Affordability", "If written off",
      ]);
      expect(screen.getByRole("tablist", { name: "Comparison views" })).toHaveClass("hidden", "sm:flex");

      await user.selectOptions(select, "affordability");
      expect(screen.getByRole("tab", { name: /affordability/i })).toHaveAttribute("aria-selected", "true");
      await user.click(screen.getByRole("tab", { name: /financing options/i }));
      expect(select).toHaveValue("financing");
    });

    it("prefills tenure and mileage band from the user's saved baseline", async () => {
      mockedFetchFinancialProfile.mockResolvedValue(
        makeFinancialProfile({ preferred_tenure_months: 60, annual_mileage_band: "high" }),
      );

      renderPage();

      expect(await screen.findByText("60 months")).toBeInTheDocument();
      expect(screen.getByLabelText("Mileage band")).toHaveValue("high");
      await waitFor(() =>
        expect(mockedFetchComparison).toHaveBeenCalledWith(
          expect.objectContaining({ tenureMonths: 60, mileageBand: "high" }),
        ),
      );
    });

    it("still prefills from a profile saved with an OLD literal-km mileage value (maps to the nearest band)", async () => {
      mockedFetchFinancialProfile.mockResolvedValue(
        makeFinancialProfile({ preferred_tenure_months: 24, annual_mileage_band: "10000" as never }),
      );

      renderPage();

      expect(await screen.findByText("24 months")).toBeInTheDocument();
      expect(screen.getByLabelText("Mileage band")).toHaveValue("standard");
    });

    it("keeps the shared 48-month / standard defaults when there is no saved profile", async () => {
      mockedFetchFinancialProfile.mockResolvedValue(null);

      renderPage();

      expect(await screen.findByText("48 months")).toBeInTheDocument();
      expect(screen.getByLabelText("Mileage band")).toHaveValue("standard");
    });

    it("keeps the hardcoded defaults when the profile fetch itself fails (silent, non-blocking)", async () => {
      mockedFetchFinancialProfile.mockRejectedValue(new Error("network down"));

      renderPage();

      expect(await screen.findByText("48 months")).toBeInTheDocument();
      expect(screen.getByLabelText("Mileage band")).toHaveValue("standard");
    });
  });

  it("labels the Hire Purchase rate flat and shows the effective rate beside it", async () => {
    mockedFetchVehicleDetail.mockResolvedValueOnce(makeVehicle());
    const comparison = makeComparisonResult();
    comparison.hire_purchase!.effective_rate_percent = "5.6000";
    mockedFetchComparison.mockResolvedValueOnce(comparison);

    renderPage();

    expect(await screen.findByText("3.00% flat p.a.")).toBeInTheDocument();
    expect(screen.getByText("≈ 5.60% effective p.a.")).toBeInTheDocument();
    expect(screen.queryByText(/Profit rate/)).not.toBeInTheDocument();
  });

  it("says 'Profit rate' (with the indicative note) when the saved profile prefers Islamic financing - figures unchanged", async () => {
    mockedFetchFinancialProfile.mockResolvedValue(makeFinancialProfile({ shariah_compliant_required: true }));
    mockedFetchVehicleDetail.mockResolvedValueOnce(makeVehicle());
    mockedFetchComparison.mockResolvedValueOnce(makeComparisonResult());

    renderPage();

    expect(await screen.findByText("Profit rate 3.00% flat p.a.")).toBeInTheDocument();
    // FX-2 (item 7): on the HP card and in "Flat vs effective rate" (was exactly one copy).
    expect(screen.getAllByText("Indicative: Islamic financing is not priced separately in this app.")).toHaveLength(2);
    expect(screen.getByText("RM 10,900.00")).toBeInTheDocument(); // HP monthly, same as without the preference
  });

  it("hides the Subscription offset footnote when the API can't cost the vehicle (offset is null), keeping the fee", async () => {
    mockedFetchVehicleDetail.mockResolvedValueOnce(makeVehicle());
    mockedFetchComparison.mockResolvedValueOnce(
      makeComparisonResult({
        subscription: {
          monthly_instalment: "2000.00",
          upfront_cash: "0.00",
          total_contract_outlay: "72000.00",
          net_cost_after_bundled_benefits: null,
          net_cost_unavailable_reason:
            "Reference Model X is missing its specs (powertrain / engine capacity). Complete them in Fleet Management.",
        },
      }),
    );

    renderPage();

    expect(await screen.findByText("RM 2,000.00")).toBeInTheDocument(); // the fee itself still shows
    expect(screen.getByText("RM 72,000.00")).toBeInTheDocument();
    expect(screen.queryByText(/Effective cost after bundled insurance/)).not.toBeInTheDocument();
  });

  it("renders all three pathways with the figures the API returned, once loaded", async () => {
    mockedFetchVehicleDetail.mockResolvedValueOnce(makeVehicle());
    mockedFetchComparison.mockResolvedValueOnce(makeComparisonResult());

    renderPage();

    expect(await screen.findByText("RM 10,900.00")).toBeInTheDocument(); // HP monthly
    expect(screen.getAllByText("RM 432,400.00")).toHaveLength(2); // HP total outlay AND GFV total outlay (H9)
    expect(screen.getByText("RM 5,344.44")).toBeInTheDocument(); // GFV monthly
    expect(screen.getByText("RM 2,000.00")).toBeInTheDocument(); // Subscription monthly (H8: gross fee)
    expect(screen.getByText("RM 72,000.00")).toBeInTheDocument(); // Subscription total outlay
    expect(screen.getByText("RM 1,450.00")).toBeInTheDocument(); // net_cost_after_bundled_benefits footnote

    // Fields that don't fit the shared table columns must still surface.
    expect(screen.getByText("3.00% flat p.a.")).toBeInTheDocument(); // the dealer's flat rate, now labelled as such
    expect(screen.getByText("50.00% residual")).toBeInTheDocument();
    // Redesign UI-3: the balloon shows twice - the GFV card's "Balloon at month N" fact and
    // the sentence in "What happens at the end of GFV" (it was once, under the table).
    expect(screen.getAllByText("RM 200,000.00")).toHaveLength(2); // balloon payment

    expect(mockedFetchComparison).toHaveBeenCalledWith(
      expect.objectContaining({ vehicle: 1, tenureMonths: 48, mileageBand: "standard" }),
    );
  });

  it("QA audit L5: the tenure slider moves in single-month steps, not just 12-month increments", async () => {
    mockedFetchVehicleDetail.mockResolvedValueOnce(makeVehicle());
    mockedFetchComparison.mockResolvedValueOnce(makeComparisonResult());

    renderPage();
    await screen.findByText("RM 10,900.00");

    expect(screen.getByLabelText("Tenure")).toHaveAttribute("step", "1");

    mockedFetchComparison.mockResolvedValueOnce(makeComparisonResult({ tenure_months: 37 }));
    fireEvent.change(screen.getByLabelText("Tenure"), { target: { value: "37" } });

    await screen.findByText("37 months");
    expect(mockedFetchComparison).toHaveBeenLastCalledWith(expect.objectContaining({ tenureMonths: 37 }));
  });

  it("shows the loading skeleton while the comparison request is in flight", async () => {
    mockedFetchVehicleDetail.mockResolvedValueOnce(makeVehicle());
    mockedFetchComparison.mockReturnValueOnce(new Promise(() => {})); // never resolves

    renderPage();

    expect(await screen.findAllByRole("status", { name: "Loading" })).not.toHaveLength(0);
  });

  it("shows UC005's alternate-flow detail message verbatim on a 400 response", async () => {
    mockedFetchVehicleDetail.mockResolvedValueOnce(makeVehicle());
    mockedFetchComparison.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 400,
        data: { detail: "No active interest rate is configured for this brand." },
      },
    });

    renderPage();

    expect(
      await screen.findByText("No active interest rate is configured for this brand."),
    ).toBeInTheDocument();
  });

  it("QA audit M13: surfaces a DRF field error for downpayment (e.g. excess decimals), not the generic fallback", async () => {
    mockedFetchVehicleDetail.mockResolvedValueOnce(makeVehicle());
    mockedFetchComparison.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 400,
        data: { downpayment: ["Ensure that there are no more than 2 decimal places."] },
      },
    });

    renderPage();

    expect(
      await screen.findByText("Ensure that there are no more than 2 decimal places."),
    ).toBeInTheDocument();
  });

  it("re-fetches with updated params when the tenure slider changes", async () => {
    mockedFetchVehicleDetail.mockResolvedValueOnce(makeVehicle());
    mockedFetchComparison.mockResolvedValue(makeComparisonResult());

    renderPage();
    await screen.findByText("RM 10,900.00");
    expect(mockedFetchComparison).toHaveBeenCalledTimes(1);

    fireEvent.change(screen.getByLabelText("Tenure"), { target: { value: "60" } });

    await screen.findByText("RM 10,900.00");
    expect(mockedFetchComparison).toHaveBeenCalledTimes(2);
    expect(mockedFetchComparison).toHaveBeenLastCalledWith(
      expect.objectContaining({ tenureMonths: 60 }),
    );
  });

  it("re-fetches with updated params when the mileage band select changes", async () => {
    mockedFetchVehicleDetail.mockResolvedValueOnce(makeVehicle());
    mockedFetchComparison.mockResolvedValue(makeComparisonResult());

    const user = userEvent.setup();
    renderPage();
    await screen.findByText("RM 10,900.00");
    expect(mockedFetchComparison).toHaveBeenCalledTimes(1);

    await user.selectOptions(screen.getByLabelText("Mileage band"), "high");

    await screen.findByText("RM 10,900.00");
    expect(mockedFetchComparison).toHaveBeenCalledTimes(2);
    expect(mockedFetchComparison).toHaveBeenLastCalledWith(
      expect.objectContaining({ mileageBand: "high" }),
    );
  });

  describe("TCO Breakdown & Depreciation tab", () => {
    async function switchToTcoTab() {
      const user = userEvent.setup();
      const tab = await screen.findByRole("tab", { name: /total cost/i });
      await user.click(tab);
    }

    beforeEach(() => {
      mockedFetchVehicleDetail.mockResolvedValue(makeVehicle());
      mockedFetchComparison.mockResolvedValue(makeComparisonResult());
    });

    it("does not fetch the TCO report until the tab is actually selected", async () => {
      mockedFetchTcoReport.mockResolvedValueOnce(makeTcoReport());

      renderPage();
      await screen.findByText("RM 10,900.00"); // financing tab has loaded

      expect(mockedFetchTcoReport).not.toHaveBeenCalled();

      await switchToTcoTab();

      expect(await screen.findByText("Remaining loan vs. predicted car value")).toBeInTheDocument();
      expect(mockedFetchTcoReport).toHaveBeenCalledTimes(1);
    });

    it("renders the negative-equity chart with both series once loaded", async () => {
      mockedFetchTcoReport.mockResolvedValueOnce(makeTcoReport());

      const { container } = renderPage();
      await switchToTcoTab();

      await screen.findByText("Remaining loan vs. predicted car value");
      const lines = container.querySelectorAll("path.recharts-line-curve");
      expect(lines).toHaveLength(2);
    });

    it("shows the TCO summary figures, correctly formatted", async () => {
      mockedFetchTcoReport.mockResolvedValueOnce(makeTcoReport());

      renderPage();
      await switchToTcoTab();

      expect(await screen.findByText("RM 10,900.00")).toBeInTheDocument(); // hp_monthly
      expect(screen.getByText("RM 612,400.00")).toBeInTheDocument(); // tco_gross
      expect(screen.getByText("RM 452,400.00")).toBeInTheDocument(); // tco_net
      expect(screen.getByText("RM 90.00 / yr")).toBeInTheDocument(); // road_tax_annual
      expect(screen.getByText("RM 1,800.00 / yr")).toBeInTheDocument(); // insurance_annual
      expect(screen.getByText("RM 600.00 / yr")).toBeInTheDocument(); // maintenance_annual
    });

    it("shows how each operating cost was derived, plus the Peninsular and before-NCD notes", async () => {
      mockedFetchTcoReport.mockResolvedValueOnce(
        makeTcoReport({
          ncd_percent: "0.00",
          operating_cost_basis: {
            road_tax: "1,998 cc petrol, saloon - JPJ cc schedule",
            insurance: "1.8% of RM 265,800.00",
            maintenance: "1.0% of price (floor RM 1,200)",
          },
        }),
      );

      renderPage();
      await switchToTcoTab();

      expect(await screen.findByText("1,998 cc petrol, saloon - JPJ cc schedule")).toBeInTheDocument();
      expect(screen.getByText("1.8% of RM 265,800.00")).toBeInTheDocument();
      expect(screen.getByText("1.0% of price (floor RM 1,200)")).toBeInTheDocument();
      expect(
        screen.getByText(
          "Estimates for Peninsular Malaysia, private car; insurance and maintenance are planning assumptions, not quotes.",
        ),
      ).toBeInTheDocument();
      // Run 1 fix batch 3: the API applied no NCD, so the screen says so.
      expect(
        screen.getByText("Insurance shown before No-Claim Discount. Add your NCD in Financial Profile."),
      ).toBeInTheDocument();
    });

    it("still renders a frozen older payload that has no operating_cost_basis", async () => {
      mockedFetchTcoReport.mockResolvedValueOnce(makeTcoReport({ operating_cost_basis: undefined }));

      renderPage();
      await switchToTcoTab();

      expect(await screen.findByText("RM 90.00 / yr")).toBeInTheDocument();
      expect(screen.queryByText(/JPJ cc schedule/)).not.toBeInTheDocument();
    });

    it("shows the exact UC006 fallback message when model_degraded is true", async () => {
      mockedFetchTcoReport.mockResolvedValueOnce(
        makeTcoReport({
          model_degraded: true,
          degraded_reason:
            "ML forecast service unavailable. Showing standardized linear depreciation model.",
        }),
      );

      renderPage();
      await switchToTcoTab();

      expect(
        await screen.findByText(
          "ML forecast service unavailable. Showing standardized linear depreciation model.",
        ),
      ).toBeInTheDocument();
    });

    it("shows the crossover month and shortfall amount when there is a crossover", async () => {
      mockedFetchTcoReport.mockResolvedValueOnce(
        makeTcoReport({
          negative_equity_crossover_month: 42,
          negative_equity_shortfall_amount: "15000.00",
        }),
      );

      renderPage();
      await switchToTcoTab();

      const callout = await screen.findByText(/negative equity begins at month 42/i);
      expect(callout).toHaveTextContent("RM 15,000.00");
    });

    it("omits the crossover callout when there is no crossover", async () => {
      mockedFetchTcoReport.mockResolvedValueOnce(makeTcoReport());

      renderPage();
      await switchToTcoTab();

      await screen.findByText("Remaining loan vs. predicted car value");
      expect(screen.queryByText(/negative equity begins/i)).not.toBeInTheDocument();
    });

    it("renders the resale value explanation card when present", async () => {
      mockedFetchTcoReport.mockResolvedValueOnce(
        makeTcoReport({
          // ML batch 1: the base is the new price; the six factors add up to the prediction.
          resale_value_explanation: {
            base_value: 265800.0,
            contributions: {
              vehicle_age: -61965.47,
              mileage: -12244.39,
              brand_code: -696.4,
              engine_litres: -3000.0,
              body_type: 2000.0,
              recond: 0.0,
            },
            predicted_value: 189893.74,
          },
        }),
      );

      renderPage();
      await switchToTcoTab();

      expect(await screen.findByText("Why this predicted value?")).toBeInTheDocument();
      expect(
        screen.getByText(
          "How much each factor moved the value from the new price (worked out on a log scale and shared in proportion).",
        ),
      ).toBeInTheDocument();
      for (const label of ["Age", "Mileage", "Brand tier", "Engine size", "Body type"]) {
        expect(screen.getByText(label)).toBeInTheDocument();
      }
      // Run 2 fix batch 3: a factor that reads RM 0.00 is left out ("Recond import" is 0.00 here).
      expect(screen.queryByText("Recond import")).not.toBeInTheDocument();
      expect(screen.queryByText("Vehicle price")).not.toBeInTheDocument();
      expect(screen.getByText("New price")).toBeInTheDocument();
      expect(screen.getByText("RM 265,800.00")).toBeInTheDocument(); // base_value
      expect(screen.getByText("RM 189,893.74")).toBeInTheDocument(); // predicted_value
      expect(screen.getByText("-RM 61,965.47")).toBeInTheDocument(); // negative contribution
      expect(screen.getByText("+RM 2,000.00")).toBeInTheDocument(); // positive contribution
    });

    it("renders nothing for the explanation when resale_value_explanation is null", async () => {
      mockedFetchTcoReport.mockResolvedValueOnce(makeTcoReport({ resale_value_explanation: null }));

      renderPage();
      await switchToTcoTab();

      await screen.findByText("Remaining loan vs. predicted car value");
      expect(screen.queryByText("Why this predicted value?")).not.toBeInTheDocument();
    });

    it("shows the loading skeleton while the TCO request is in flight", async () => {
      mockedFetchTcoReport.mockReturnValueOnce(new Promise(() => {})); // never resolves

      renderPage();
      await switchToTcoTab();

      expect(await screen.findAllByRole("status", { name: "Loading" })).not.toHaveLength(0);
    });

    it("shows the detail message verbatim on a 400 response", async () => {
      mockedFetchTcoReport.mockRejectedValueOnce({
        isAxiosError: true,
        response: {
          status: 400,
          data: { detail: "No operating-cost band is configured for this engine capacity." },
        },
      });

      renderPage();
      await switchToTcoTab();

      expect(
        await screen.findByText("No operating-cost band is configured for this engine capacity."),
      ).toBeInTheDocument();
    });
  });

  describe("AI Recommendation tab", () => {
    async function switchToRecommendationTab() {
      const user = userEvent.setup();
      const tab = await screen.findByRole("tab", { name: /ai recommendation/i });
      await user.click(tab);
    }

    function fillQuiz() {
      fireEvent.change(screen.getByLabelText("Upfront cash preservation"), { target: { value: "5" } });
      // 4, not 3 - RangeSlider's "unanswered" fallback display defaults
      // to 3, and fireEvent.change is a no-op when the target value
      // matches what's already rendered (React's controlled-input value
      // tracker sees no change), so 3 would never actually register.
      fireEvent.change(screen.getByLabelText("Maintenance protection"), { target: { value: "4" } });
      fireEvent.change(screen.getByLabelText("Ownership equity"), { target: { value: "2" } });
      fireEvent.change(screen.getByLabelText("Monthly income (gross, RM)"), { target: { value: "8000" } });
      fireEvent.change(screen.getByLabelText("Max DSR limit (%)"), { target: { value: "60" } });
    }

    beforeEach(() => {
      mockedFetchVehicleDetail.mockResolvedValue(makeVehicle());
      mockedFetchComparison.mockResolvedValue(makeComparisonResult());
    });

    it("does not fetch a recommendation until all three ratings, income, and DSR are filled in", async () => {
      renderPage();
      await switchToRecommendationTab();

      expect(
        screen.getByText("Please rate all three priorities to receive a recommendation."),
      ).toBeInTheDocument();
      expect(mockedFetchScoring).not.toHaveBeenCalled();

      fireEvent.change(screen.getByLabelText("Upfront cash preservation"), { target: { value: "5" } });
      // 4, not 3 - RangeSlider's "unanswered" fallback display defaults
      // to 3, and fireEvent.change is a no-op when the target value
      // matches what's already rendered (React's controlled-input value
      // tracker sees no change), so 3 would never actually register.
      fireEvent.change(screen.getByLabelText("Maintenance protection"), { target: { value: "4" } });
      fireEvent.change(screen.getByLabelText("Ownership equity"), { target: { value: "2" } });

      expect(
        screen.getByText("Enter your monthly income and maximum DSR limit to see a recommendation."),
      ).toBeInTheDocument();
      expect(mockedFetchScoring).not.toHaveBeenCalled();

      mockedFetchScoring.mockResolvedValueOnce(makeScoringResult());
      fireEvent.change(screen.getByLabelText("Monthly income (gross, RM)"), { target: { value: "8000" } });
      fireEvent.change(screen.getByLabelText("Max DSR limit (%)"), { target: { value: "60" } });

      await screen.findByText(/subscription best matches/i);
      expect(mockedFetchScoring).toHaveBeenCalledTimes(1);
    });

    it("renders pathways in ranking order with scores/DSR badges and highlights the recommended one", async () => {
      mockedFetchScoring.mockResolvedValueOnce(makeScoringResult());

      renderPage();
      await switchToRecommendationTab();
      fillQuiz();

      expect(await screen.findByText(/subscription best matches your priorities/i)).toBeInTheDocument();

      // Redesign UI-3: the ranking is an ordered list under "Full ranking" (each
      // pathway was its own level-3 card heading), after the "Best match" card.
      const ranking = await screen.findByRole("list", { name: "Full ranking" });
      expect(
        Array.from(ranking.querySelectorAll("[data-ranking-name]")).map((name) => name.textContent?.trim()),
      ).toEqual(["Subscription", "Hire Purchase", "GFV Leasing"]);
      expect(screen.getByText("Best match").nextElementSibling).toHaveTextContent("Subscription");

      expect(screen.getByText("Recommended")).toBeInTheDocument();
      expect(screen.getAllByText("Exceeds DSR")).toHaveLength(2);
      expect(screen.getByText("83.33%")).toBeInTheDocument(); // subscription's suitability_score
    });

    // Redesign UI-3: the Financing options cards carry "Recommended" only from the
    // scoring API's own result for these inputs - never worked out in the browser.
    it("marks the API's recommended pathway on the Financing options cards once a result exists", async () => {
      mockedFetchScoring.mockResolvedValue(makeScoringResult());
      const user = userEvent.setup();

      renderPage();
      await screen.findByText("RM 10,900.00");
      expect(screen.queryByText("Recommended")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Rate your priorities" })).toBeInTheDocument();

      await switchToRecommendationTab();
      fillQuiz();
      await screen.findByText(/subscription best matches/i);
      await user.click(await screen.findByRole("tab", { name: "Financing options" }));

      const subscription = await screen.findByRole("article", { name: "Subscription" });
      expect(within(subscription).getByText("Recommended")).toBeInTheDocument();
      expect(screen.getAllByText("Recommended")).toHaveLength(1);
      expect(screen.queryByRole("button", { name: "Rate your priorities" })).not.toBeInTheDocument();
    });

    it("opens the AI recommendation tab from 'Rate your priorities'", async () => {
      const user = userEvent.setup();

      renderPage();
      await screen.findByText("RM 10,900.00");
      await user.click(screen.getByRole("button", { name: "Rate your priorities" }));

      expect(screen.getByRole("tab", { name: /ai recommendation/i })).toHaveAttribute("aria-selected", "true");
    });

    it("shows the incomplete-quiz message from a .priorities 400 error verbatim", async () => {
      mockedFetchScoring.mockRejectedValueOnce({
        isAxiosError: true,
        response: {
          status: 400,
          data: { priorities: ["Please rate all three priorities to receive a recommendation."] },
        },
      });

      renderPage();
      await switchToRecommendationTab();
      fillQuiz();

      expect(
        await screen.findByText("Please rate all three priorities to receive a recommendation."),
      ).toBeInTheDocument();
    });

    it("shows the all-pathways-excluded rationale verbatim when recommended_pathway is null", async () => {
      mockedFetchScoring.mockResolvedValueOnce(
        makeScoringResult({
          recommended_pathway: null,
          rationale: "None of the available pathways fit within your declared DSR limit.",
        }),
      );

      renderPage();
      await switchToRecommendationTab();
      fillQuiz();

      expect(
        await screen.findByText("None of the available pathways fit within your declared DSR limit."),
      ).toBeInTheDocument();
      expect(screen.queryByText("Recommended")).not.toBeInTheDocument();
    });

    it("QA audit M6: keeps quiz/income/DSR inputs after switching tabs away and back", async () => {
      mockedFetchScoring.mockResolvedValue(makeScoringResult());

      renderPage();
      await switchToRecommendationTab();
      fillQuiz();
      await screen.findByText(/subscription best matches/i);

      // Switch away (unmounts RecommendationPanel - see Tabs.Panel) and
      // back - previously every local useState (ratings/income/DSR) was
      // wiped on unmount, so the quiz would show as unanswered again.
      // Tabs.Panel's lazy-mount design is deliberately unchanged (see
      // TcoPanel's own comment on why), so remounting still re-fetches -
      // what must NOT happen is the quiz looking unanswered again.
      const user = userEvent.setup();
      await user.click(await screen.findByRole("tab", { name: "Financing options" }));
      await user.click(await screen.findByRole("tab", { name: /ai recommendation/i }));

      expect(screen.queryByText("Not yet rated")).not.toBeInTheDocument();
      expect(screen.getByLabelText("Monthly income (gross, RM)")).toHaveValue(8000);
      expect(screen.getByLabelText("Max DSR limit (%)")).toHaveValue(60);
      expect(await screen.findByText(/subscription best matches/i)).toBeInTheDocument();
      // Both fetches (initial + remount) used the SAME inputs - nothing
      // reverted to an earlier/unanswered state in between.
      const [firstCallArgs] = mockedFetchScoring.mock.calls[0];
      const lastCallArgs = mockedFetchScoring.mock.calls.at(-1)?.[0];
      expect(lastCallArgs).toEqual(firstCallArgs);
    });
  });

  describe("Export as PDF", () => {
    beforeEach(() => {
      mockedFetchVehicleDetail.mockResolvedValue(makeVehicle());
    });

    it("disables the button until a comparison result exists", async () => {
      mockedFetchComparison.mockReturnValueOnce(new Promise(() => {})); // never resolves

      renderPage();

      expect(await screen.findByRole("button", { name: "Export as PDF" })).toBeDisabled();
    });

    it("triggers a download and shows a confirmation message on success", async () => {
      mockedFetchComparison.mockResolvedValue(makeComparisonResult());
      mockedExportComparisonPdf.mockResolvedValueOnce({ blob: new Blob(["%PDF fake"], { type: "application/pdf" }), filename: null });

      renderPage();
      await screen.findByText("RM 10,900.00"); // comparison loaded, button now enabled

      const user = userEvent.setup();
      await user.click(screen.getByRole("button", { name: "Export as PDF" }));

      expect(await screen.findByText("Your PDF download has started.")).toBeInTheDocument();
      // C4: only the same inputs the comparison itself used are sent -
      // never pathway figures (the server recomputes those itself).
      expect(mockedExportComparisonPdf).toHaveBeenCalledWith(
        expect.objectContaining({
          vehicle: 1,
          tenureMonths: 48,
          mileageBand: "standard",
          downpayment: "40000.00",
          // QA audit M16: the default tab is "Financing Pathways", where
          // no chart is mounted - the capture must fall back to "", not
          // omit the key or throw.
          chartSvg: "",
        }),
      );
    });

    it("captures the live TCO chart's SVG markup when exporting from the TCO tab", async () => {
      mockedFetchComparison.mockResolvedValue(makeComparisonResult());
      mockedFetchTcoReport.mockResolvedValueOnce(makeTcoReport());
      mockedExportComparisonPdf.mockResolvedValueOnce({ blob: new Blob(["%PDF fake"], { type: "application/pdf" }), filename: null });

      renderPage();
      await screen.findByText("RM 10,900.00");

      const user = userEvent.setup();
      await user.click(await screen.findByRole("tab", { name: /total cost/i }));
      await screen.findByText("Remaining loan vs. predicted car value");

      await user.click(screen.getByRole("button", { name: "Export as PDF" }));

      expect(await screen.findByText("Your PDF download has started.")).toBeInTheDocument();
      const { chartSvg } = mockedExportComparisonPdf.mock.calls[0][0];
      expect(chartSvg).toContain("<svg");
      expect(chartSvg).toContain("recharts-surface");
      // Run 1 fix batch 2: the chart itself (both lines), not a legend icon -
      // the legend's icon <svg>s come first in the DOM and also carry
      // "recharts-surface", so the checks above alone passed for an icon.
      expect(chartSvg).not.toContain("legend icon");
      expect(chartSvg?.match(/recharts-line-curve/g)).toHaveLength(2);
    });

    it("surfaces the parsed .detail message from a 504 blob error response", async () => {
      mockedFetchComparison.mockResolvedValue(makeComparisonResult());
      const errorBlob = new Blob(
        [
          JSON.stringify({
            detail: "PDF export failed due to a server generation timeout. Please try downloading again.",
          }),
        ],
        { type: "application/json" },
      );
      mockedExportComparisonPdf.mockRejectedValueOnce({
        isAxiosError: true,
        response: { status: 504, data: errorBlob },
      });

      renderPage();
      await screen.findByText("RM 10,900.00");

      const user = userEvent.setup();
      await user.click(screen.getByRole("button", { name: "Export as PDF" }));

      expect(
        await screen.findByText(
          "PDF export failed due to a server generation timeout. Please try downloading again.",
        ),
      ).toBeInTheDocument();
    });

    it("QA audit L3: clears a stale export error once the inputs change", async () => {
      mockedFetchComparison.mockResolvedValue(makeComparisonResult());
      mockedExportComparisonPdf.mockRejectedValueOnce({
        isAxiosError: true,
        response: { status: 504, data: new Blob([JSON.stringify({ detail: "Timed out." })]) },
      });

      renderPage();
      await screen.findByText("RM 10,900.00");

      const user = userEvent.setup();
      await user.click(screen.getByRole("button", { name: "Export as PDF" }));
      expect(await screen.findByText("Timed out.")).toBeInTheDocument();

      fireEvent.change(screen.getByLabelText("Tenure"), { target: { value: "60" } });

      expect(screen.queryByText("Timed out.")).not.toBeInTheDocument();
    });
  });

  describe("H14: Save/Export must never use stale data from before an input change", () => {
    beforeEach(() => {
      mockedFetchVehicleDetail.mockResolvedValue(makeVehicle());
    });

    it("disables both buttons the instant tenure changes, and uses the NEW result once re-enabled", async () => {
      mockedFetchComparison.mockResolvedValueOnce(makeComparisonResult());
      mockedExportComparisonPdf.mockResolvedValue({ blob: new Blob(["%PDF fake"], { type: "application/pdf" }), filename: null });

      renderPage();
      await screen.findByText("RM 10,900.00");

      expect(screen.getByRole("button", { name: "Export as PDF" })).not.toBeDisabled();
      expect(screen.getByRole("button", { name: "Save this Comparison" })).not.toBeDisabled();

      let resolveSecondFetch!: (value: ComparisonResult) => void;
      const secondFetch = new Promise<ComparisonResult>((resolve) => {
        resolveSecondFetch = resolve;
      });
      mockedFetchComparison.mockReturnValueOnce(secondFetch);

      fireEvent.change(screen.getByLabelText("Tenure"), { target: { value: "60" } });

      // Immediately after the input change, BEFORE the new fetch resolves
      // - the old comparison must already be gone, not just once a
      // separate loading/error flag happens to also be checked.
      expect(screen.getByRole("button", { name: "Export as PDF" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "Save this Comparison" })).toBeDisabled();

      resolveSecondFetch(makeComparisonResult({ tenure_months: 60 }));

      await waitFor(() => {
        expect(screen.getByRole("button", { name: "Export as PDF" })).not.toBeDisabled();
      });
      expect(screen.getByRole("button", { name: "Save this Comparison" })).not.toBeDisabled();

      const user = userEvent.setup();
      await user.click(screen.getByRole("button", { name: "Export as PDF" }));

      expect(mockedExportComparisonPdf).toHaveBeenCalledWith(
        expect.objectContaining({ tenureMonths: 60 }),
      );
    });
  });

  describe("Save this Comparison", () => {
    beforeEach(() => {
      mockedFetchVehicleDetail.mockResolvedValue(makeVehicle());
    });

    it("disables the button until a comparison result exists", async () => {
      mockedFetchComparison.mockReturnValueOnce(new Promise(() => {})); // never resolves

      renderPage();

      expect(await screen.findByRole("button", { name: "Save this Comparison" })).toBeDisabled();
    });

    it("shows a confirmation message on successful save", async () => {
      mockedFetchComparison.mockResolvedValue(makeComparisonResult());
      mockedSaveScenario.mockResolvedValueOnce({
        id: 1,
        title: "My scenario",
        vehicle: 1,
        vehicle_label: "Honda City V",
        payload: {
          tenureMonths: 48,
          mileageBand: "standard",
          downpayment: "40000.00",
          comparison: makeComparisonResult(),
          tco: null,
          scoring: null,
        },
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      });

      renderPage();
      await screen.findByText("RM 10,900.00");

      const user = userEvent.setup();
      await user.click(screen.getByRole("button", { name: "Save this Comparison" }));
      await user.type(screen.getByLabelText("Comparison title"), "My scenario");
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(await screen.findByText(/^Comparison saved\./) /* FX-2 item 3: was "Comparison saved to your portfolio." */).toBeInTheDocument();
      expect(mockedSaveScenario).toHaveBeenCalledWith(
        expect.objectContaining({ title: "My scenario", vehicle: 1, overwrite: false }),
      );
    });

    it("shows the duplicate-title message on a 409 and offers an overwrite path", async () => {
      mockedFetchComparison.mockResolvedValue(makeComparisonResult());
      const duplicateMessage =
        "A comparison with this title already exists. Please choose a different title or overwrite the existing comparison.";
      mockedSaveScenario.mockRejectedValueOnce({
        isAxiosError: true,
        response: { status: 409, data: { detail: duplicateMessage } },
      });

      renderPage();
      await screen.findByText("RM 10,900.00");

      const user = userEvent.setup();
      await user.click(screen.getByRole("button", { name: "Save this Comparison" }));
      await user.type(screen.getByLabelText("Comparison title"), "Existing title");
      await user.click(screen.getByRole("button", { name: "Save" }));

      expect(await screen.findByText(duplicateMessage)).toBeInTheDocument();
      const overwriteButton = screen.getByRole("button", { name: "Overwrite existing" });

      mockedSaveScenario.mockResolvedValueOnce({
        id: 2,
        title: "Existing title",
        vehicle: 1,
        vehicle_label: "Honda City V",
        payload: {
          tenureMonths: 48,
          mileageBand: "standard",
          downpayment: "40000.00",
          comparison: makeComparisonResult(),
          tco: null,
          scoring: null,
        },
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      });
      await user.click(overwriteButton);

      expect(await screen.findByText(/^Comparison saved\./) /* FX-2 item 3: was "Comparison saved to your portfolio." */).toBeInTheDocument();
      expect(mockedSaveScenario).toHaveBeenLastCalledWith(expect.objectContaining({ overwrite: true }));
    });

    // --- Run 1 fix batch 2 (G6): Save sends inputs, never figures ----------------

    async function saveAs(title: string) {
      const user = userEvent.setup();
      await user.click(screen.getByRole("button", { name: "Save this Comparison" }));
      await user.type(screen.getByLabelText("Comparison title"), title);
      await user.click(screen.getByRole("button", { name: "Save" }));
      await screen.findByText(/^Comparison saved\./) /* FX-2 item 3: was "Comparison saved to your portfolio." */;
      return mockedSaveScenario.mock.calls[mockedSaveScenario.mock.calls.length - 1][0];
    }

    it("sends only the inputs, with no scoring request while the AI tab has no result", async () => {
      mockedFetchComparison.mockResolvedValue(makeComparisonResult());
      mockedSaveScenario.mockResolvedValueOnce({ id: 1 } as never);

      renderPage();
      await screen.findByText("RM 10,900.00");
      const sent = await saveAs("Inputs only");

      // FX-1 (X5): include_tco is always true now (it was false until the Total cost tab had a result).
      expect(sent).toEqual({
        title: "Inputs only",
        vehicle: 1,
        inputs: { tenure_months: 48, mileage_band: "standard", downpayment: "40000.00", include_tco: true, scoring: null },
        overwrite: false,
      });
      expect(sent).not.toHaveProperty("payload");
    });

    it("sends the AI tab's request once that tab has produced a result", async () => {
      mockedFetchComparison.mockResolvedValue(makeComparisonResult());
      mockedFetchScoring.mockResolvedValue(makeScoringResult());
      mockedSaveScenario.mockResolvedValueOnce({ id: 1 } as never);

      renderPage();
      await screen.findByText("RM 10,900.00");
      await userEvent.setup().click(await screen.findByRole("tab", { name: /ai recommendation/i }));
      fireEvent.change(screen.getByLabelText("Upfront cash preservation"), { target: { value: "5" } });
      fireEvent.change(screen.getByLabelText("Maintenance protection"), { target: { value: "4" } });
      fireEvent.change(screen.getByLabelText("Ownership equity"), { target: { value: "2" } });
      fireEvent.change(screen.getByLabelText("Monthly income (gross, RM)"), { target: { value: "8000" } });
      fireEvent.change(screen.getByLabelText("Max DSR limit (%)"), { target: { value: "60" } });
      await screen.findByText(/subscription best matches/i);

      const sent = await saveAs("With scoring");

      expect(sent.inputs.scoring).toEqual({
        upfront_cash_preservation: 5,
        maintenance_protection: 4,
        ownership_equity: 2,
        monthly_income: "8000",
        max_dsr_percent: "60",
      });
    });

    // FX-1 (X3): the 4B repro - rate on the AI tab with Max DSR 40, change the Max DSR to 60 on the Affordability tab,
    // save from the If-written-off tab. Save must send the CURRENT limit (it sent the AI tab's last request, DSR 40).
    async function rateAt40ThenChangeDsrOnAffordability() {
      const user = userEvent.setup();
      await user.click(await screen.findByRole("tab", { name: /ai recommendation/i }));
      fireEvent.change(screen.getByLabelText("Upfront cash preservation"), { target: { value: "5" } });
      fireEvent.change(screen.getByLabelText("Maintenance protection"), { target: { value: "4" } });
      fireEvent.change(screen.getByLabelText("Ownership equity"), { target: { value: "2" } });
      fireEvent.change(screen.getByLabelText("Monthly income (gross, RM)"), { target: { value: "12000" } });
      fireEvent.change(screen.getByLabelText("Max DSR limit (%)"), { target: { value: "40" } });
      await screen.findByText(/subscription best matches/i);
      await user.click(screen.getByRole("tab", { name: "Affordability" }));
      fireEvent.change(screen.getByLabelText("Max DSR limit (%)"), { target: { value: "60" } });
      return user;
    }

    it("saves the recommendation request with the Max DSR changed on the Affordability tab, from another tab", async () => {
      mockedFetchComparison.mockResolvedValue(makeComparisonResult());
      mockedFetchScoring.mockResolvedValue(makeScoringResult());
      mockedSaveScenario.mockResolvedValueOnce({ id: 1 } as never);

      renderPage();
      await screen.findByText("RM 10,900.00");
      const user = await rateAt40ThenChangeDsrOnAffordability();
      await user.click(screen.getByRole("tab", { name: "If written off" }));

      const sent = await saveAs("After the DSR change");

      expect(sent.inputs.scoring).toEqual({
        upfront_cash_preservation: 5,
        maintenance_protection: 4,
        ownership_equity: 2,
        monthly_income: "12000",
        max_dsr_percent: "60",
      });
      expect(sent.inputs.include_tco).toBe(true);
      // Only the AI tab's own fetch ran (for DSR 40); the saved recommendation is built by the server from the request.
      expect(mockedFetchScoring.mock.calls.every(([args]) => args.maxDsrPercent === "40")).toBe(true);
    });

    it("drops the Recommended badge once the Max DSR changes on another tab (the result was for the old limit)", async () => {
      mockedFetchComparison.mockResolvedValue(makeComparisonResult());
      mockedFetchScoring.mockResolvedValue(makeScoringResult());

      renderPage();
      await screen.findByText("RM 10,900.00");
      const user = await rateAt40ThenChangeDsrOnAffordability();
      await user.click(screen.getByRole("tab", { name: "Financing options" }));

      await screen.findByRole("article", { name: "Subscription" });
      expect(screen.queryByText("Recommended")).not.toBeInTheDocument();
    });

    it("drops the scoring request again when the quiz is no longer complete", async () => {
      mockedFetchComparison.mockResolvedValue(makeComparisonResult());
      mockedFetchScoring.mockResolvedValue(makeScoringResult());
      mockedSaveScenario.mockResolvedValueOnce({ id: 1 } as never);

      renderPage();
      await screen.findByText("RM 10,900.00");
      await userEvent.setup().click(await screen.findByRole("tab", { name: /ai recommendation/i }));
      fireEvent.change(screen.getByLabelText("Upfront cash preservation"), { target: { value: "5" } });
      fireEvent.change(screen.getByLabelText("Maintenance protection"), { target: { value: "4" } });
      fireEvent.change(screen.getByLabelText("Ownership equity"), { target: { value: "2" } });
      fireEvent.change(screen.getByLabelText("Monthly income (gross, RM)"), { target: { value: "8000" } });
      fireEvent.change(screen.getByLabelText("Max DSR limit (%)"), { target: { value: "60" } });
      await screen.findByText(/subscription best matches/i);
      fireEvent.change(screen.getByLabelText("Monthly income (gross, RM)"), { target: { value: "" } });

      const sent = await saveAs("Quiz cleared");

      expect(sent.inputs.scoring).toBeNull();
    });
  });

  // --- Run 1 fix batch 5 (M4): the compare inputs live in the URL ---------------------

  describe("Compare inputs in the URL", () => {
    beforeEach(() => {
      mockedFetchVehicleDetail.mockResolvedValue(makeVehicle());
      mockedFetchComparison.mockResolvedValue(makeComparisonResult());
    });

    it("uses a link's tenure, mileage band and downpayment - ahead of the saved profile", async () => {
      mockedFetchFinancialProfile.mockResolvedValue(
        makeFinancialProfile({ preferred_tenure_months: 36, annual_mileage_band: "low" }),
      );

      renderPage("?tenure=60&mileage=high&downpayment=50000.00");

      await waitFor(() =>
        expect(mockedFetchComparison).toHaveBeenLastCalledWith({
          vehicle: 1, tenureMonths: 60, mileageBand: "high", downpayment: "50000.00",
        }),
      );
      expect(screen.getByLabelText("Tenure")).toHaveValue("60");
      expect(screen.getByLabelText("Downpayment (RM)")).toHaveValue(50000);
    });

    it("falls back to the defaults for invalid values, with no error page", async () => {
      renderPage("?tenure=999&mileage=bogus&downpayment=abc");

      await waitFor(() =>
        expect(mockedFetchComparison).toHaveBeenLastCalledWith({
          vehicle: 1, tenureMonths: 48, mileageBand: "standard", downpayment: "40000.00",
        }),
      );
      expect(await screen.findByText("RM 10,900.00")).toBeInTheDocument();
      expect(screen.queryByText(/could not be found/i)).not.toBeInTheDocument();
    });

    it("uses the car's minimum when a link's downpayment is below it", async () => {
      renderPage("?downpayment=1000.00");

      await waitFor(() =>
        expect(mockedFetchComparison).toHaveBeenLastCalledWith(expect.objectContaining({ downpayment: "40000.00" })),
      );
    });

    it("writes the inputs back to the URL, so a refresh or a copied link keeps them", async () => {
      renderPage();
      await screen.findByText("RM 10,900.00");

      await waitFor(() =>
        expect(screen.getByTestId("location-search")).toHaveTextContent(
          "?tenure=48&mileage=standard&downpayment=40000.00",
        ),
      );
      fireEvent.change(screen.getByLabelText("Tenure"), { target: { value: "60" } });
      await waitFor(() => expect(screen.getByTestId("location-search")).toHaveTextContent("tenure=60"));
    });
  });

  // --- Run 1 fix batch 5 (A5): income and DSR limit from the profile -----------------

  it("starts the AI Recommendation inputs from the profile's income and DSR limit, still editable", async () => {
    mockedFetchVehicleDetail.mockResolvedValue(makeVehicle());
    mockedFetchComparison.mockResolvedValue(makeComparisonResult());
    mockedFetchFinancialProfile.mockResolvedValue(
      makeFinancialProfile({ monthly_income: "8000.00", max_dsr_percent: "45.00" }),
    );
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("RM 10,900.00");
    await user.click(await screen.findByRole("tab", { name: /ai recommendation/i }));

    const income = screen.getByLabelText("Monthly income (gross, RM)");
    expect(income).toHaveValue(8000);
    expect(screen.getByLabelText("Max DSR limit (%)")).toHaveValue(45);
    await user.clear(income);
    await user.type(income, "9000");
    expect(income).toHaveValue(9000);
  });
});

describe("ComparisonPage (FX-2)", () => {
  beforeEach(() => {
    mockedFetchVehicleDetail.mockReset();
    mockedFetchComparison.mockReset();
    mockedFetchFinancialProfile.mockReset();
    mockedFetchFinancialProfile.mockResolvedValue(null);
  });

  // item 1
  it("a network failure says the server can't be reached, and Try again loads the car", async () => {
    mockedFetchVehicleDetail.mockRejectedValueOnce({ isAxiosError: true, message: "Network Error" }).mockResolvedValueOnce(makeVehicle());
    mockedFetchComparison.mockResolvedValue(makeComparisonResult());
    const user = userEvent.setup();

    renderPage();

    expect(await screen.findByText("We can't reach the server right now. Check your connection and try again.")).toBeInTheDocument();
    expect(screen.queryByText("Vehicle not found")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("RM 10,900.00")).toBeInTheDocument();
  });

  it("only a real 404 says the vehicle could not be found, with no Try again", async () => {
    mockedFetchVehicleDetail.mockRejectedValueOnce({ isAxiosError: true, response: { status: 404, data: { detail: "Not found." } } });

    renderPage();

    expect(await screen.findByText("This vehicle could not be found.")).toBeInTheDocument();
    expect(screen.getByText("Vehicle not found")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  // item 4
  it("labels the tenure ticks and repeats the API's own 'not offered' reasons under the slider", async () => {
    const gfvReason = "GFV leasing isn't offered for 72 months - it is offered for 12 to 60 months in 12-month steps.";
    const subReason = "Subscription plans run for 12, 24 or 36 months.";
    mockedFetchVehicleDetail.mockResolvedValue(makeVehicle());
    mockedFetchComparison.mockResolvedValue(
      makeComparisonResult({
        tenure_months: 72,
        gfv_leasing: null,
        subscription: null,
        unavailable: { gfv_leasing: gfvReason, subscription: subReason },
      }),
    );

    renderPage("?tenure=72");

    const slider = await screen.findByRole("slider", { name: "Tenure" });
    await vi.waitFor(() => expect(slider).toHaveAccessibleDescription(`${gfvReason} ${subReason}`));
    const list = document.getElementById(slider.getAttribute("list")!)!;
    expect(Array.from(list.querySelectorAll("option")).map((o) => o.getAttribute("value"))).toEqual(["12", "24", "36", "48", "60"]);
  });

  it("shows no hint when every option is offered", async () => {
    mockedFetchVehicleDetail.mockResolvedValue(makeVehicle());
    mockedFetchComparison.mockResolvedValue(makeComparisonResult());

    renderPage();
    await screen.findByText("RM 10,900.00");

    expect(screen.getByRole("slider", { name: "Tenure" })).not.toHaveAttribute("aria-describedby");
  });

  // item 5
  it("a downpayment of exactly the price reads as buying outright; above the price keeps the old sentence", async () => {
    mockedFetchVehicleDetail.mockResolvedValue(makeVehicle());
    mockedFetchComparison.mockResolvedValue(makeComparisonResult());

    renderPage();
    await screen.findByText("RM 10,900.00");
    const downpayment = screen.getByLabelText("Downpayment (RM)");

    fireEvent.change(downpayment, { target: { value: "400000" } });
    expect(
      await screen.findByText("Buying outright? With a 100% downpayment there is nothing to finance, so these options don't apply."),
    ).toBeInTheDocument();

    fireEvent.change(downpayment, { target: { value: "400001" } });
    expect(await screen.findByText("Downpayment must be less than the vehicle's price.")).toBeInTheDocument();
  });
});
