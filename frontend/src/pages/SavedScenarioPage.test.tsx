import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { SavedScenarioPage } from "./SavedScenarioPage";
import { deleteScenario, getScenario } from "../api/scenarios";
import { fetchComparison } from "../api/comparisons";
import { fetchTcoReport } from "../api/depreciation";
import { fetchScoring } from "../api/scoring";
import type { ComparisonResult } from "../types/comparisons";
import type { TcoReport } from "../types/depreciation";
import type { ScoringResult } from "../types/scoring";
import type { Scenario } from "../types/scenarios";
import { PRE_BATCH6_STANDARD_INCLUDED_KM, PRE_BATCH6_STANDARD_MILEAGE_NOTE } from "../test/mileageBandsFixture";

// This suite is what actually protects UC009's "reload from stored
// payload" requirement - SavedScenarioPage must render entirely from
// GET /api/scenarios/:id/'s response and never call any of these three
// live-calculation endpoints, even though they're mocked and available.
vi.mock("../api/scenarios", () => ({
  getScenario: vi.fn(),
  deleteScenario: vi.fn(),
}));
vi.mock("../api/comparisons", () => ({
  fetchComparison: vi.fn(),
}));
vi.mock("../api/depreciation", () => ({
  fetchTcoReport: vi.fn(),
}));
vi.mock("../api/scoring", () => ({
  fetchScoring: vi.fn(),
}));

const mockedGetScenario = vi.mocked(getScenario);
const mockedDeleteScenario = vi.mocked(deleteScenario);
const mockedFetchComparison = vi.mocked(fetchComparison);
const mockedFetchTcoReport = vi.mocked(fetchTcoReport);
const mockedFetchScoring = vi.mocked(fetchScoring);

// The exact example response from F005's API contract.
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
      // QA audit H9: includes the 200000.00 balloon (L7 true-up:
      // 40000 + 5344.4444...*36 = 232400.00, + balloon = 432400.00).
      total_contract_outlay: "432400.00",
      balloon_payment: "200000.00",
      residual_value_ratio: "0.5000",
    },
    subscription: {
      // QA audit H8: the real, gross fee billed.
      monthly_instalment: "2000.00",
      upfront_cash: "0.00",
      total_contract_outlay: "72000.00",
      net_cost_after_bundled_benefits: "1450.00",
    },
    unavailable: {},
    ...overrides,
  };
}

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
        monthly_instalment: "1450.00",
        upfront_cash: "0.00",
        dsr_percent: "18.13",
        exceeds_dsr: false,
        suitability_score: "83.33",
      },
    },
    ranking: ["subscription", "hire_purchase", "gfv_leasing"],
    recommended_pathway: "subscription",
    rationale: "Subscription best matches your priorities, scoring 83.33% suitability.",
    unavailable: {},
    ...overrides,
  };
}

function makeScenario(overrides: Partial<Scenario> = {}): Scenario {
  return {
    id: 1,
    title: "Honda City comparison",
    vehicle: 1,
    vehicle_label: "Honda City V",
    payload: {
      tenureMonths: 36,
      mileageBand: "standard",
      downpayment: "40000.00",
      comparison: makeComparisonResult(),
      tco: null,
      scoring: null,
    },
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-02-15T00:00:00Z",
    ...overrides,
  };
}

function renderPage(scenarioId = "1") {
  return render(
    <MemoryRouter initialEntries={[`/scenarios/${scenarioId}`]}>
      <Routes>
        <Route path="/scenarios/:id" element={<SavedScenarioPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("SavedScenarioPage", () => {
  beforeEach(() => {
    mockedGetScenario.mockReset();
    mockedDeleteScenario.mockReset();
    mockedFetchComparison.mockReset();
    mockedFetchTcoReport.mockReset();
    mockedFetchScoring.mockReset();
  });

  it("renders the pathway table from the stored payload without calling any live calculation endpoint", async () => {
    mockedGetScenario.mockResolvedValueOnce(makeScenario());

    renderPage();

    expect(await screen.findByText("Honda City comparison")).toBeInTheDocument();
    expect(screen.getByText(/Honda City V/)).toBeInTheDocument();
    expect(screen.getByText("RM 10,900.00")).toBeInTheDocument(); // HP monthly
    expect(screen.getByText("RM 5,344.44")).toBeInTheDocument(); // GFV monthly
    expect(screen.getByText("RM 2,000.00")).toBeInTheDocument(); // Subscription monthly (H8: gross fee)
    expect(screen.getByText("RM 1,450.00")).toBeInTheDocument(); // net_cost_after_bundled_benefits footnote

    expect(mockedFetchComparison).not.toHaveBeenCalled();
    expect(mockedFetchTcoReport).not.toHaveBeenCalled();
    expect(mockedFetchScoring).not.toHaveBeenCalled();
  });

  it("renders an old snapshot (saved before effective rates existed): flat label, no effective figure, no error", async () => {
    mockedGetScenario.mockResolvedValueOnce(makeScenario()); // comparison has no effective_rate_percent

    renderPage();

    expect(await screen.findByText("3.00% flat p.a.")).toBeInTheDocument();
    expect(screen.queryByText(/effective p\.a\./)).not.toBeInTheDocument();
    expect(screen.queryByText(/Profit rate/)).not.toBeInTheDocument();
  });

  it("shows the effective rate and the saved Islamic-financing wording from a newer snapshot - still one API call", async () => {
    const comparison = makeComparisonResult();
    comparison.hire_purchase!.effective_rate_percent = "5.6000";
    mockedGetScenario.mockResolvedValueOnce(
      makeScenario({
        payload: {
          tenureMonths: 36,
          mileageBand: "standard",
          downpayment: "40000.00",
          comparison,
          tco: null,
          scoring: null,
          prefersIslamicFinancing: true,
        },
      }),
    );

    renderPage();

    expect(await screen.findByText("Profit rate 3.00% flat p.a.")).toBeInTheDocument();
    expect(screen.getByText("≈ 5.60% effective p.a.")).toBeInTheDocument();
    // FX-2 (item 7): on the HP card and in "Flat vs effective rate" (was exactly one copy).
    expect(screen.getAllByText("Indicative: Islamic financing is not priced separately in this app.")).toHaveLength(2);
    expect(mockedFetchComparison).not.toHaveBeenCalled();
  });

  it("omits the TCO and recommendation sections when absent from the payload", async () => {
    mockedGetScenario.mockResolvedValueOnce(makeScenario()); // tco: null, scoring: null

    renderPage();

    await screen.findByText("Honda City comparison");
    expect(screen.queryByText("TCO Breakdown & Depreciation")).not.toBeInTheDocument();
    expect(screen.queryByText("AI Recommendation")).not.toBeInTheDocument();
  });

  it("renders the TCO section from the stored payload when present", async () => {
    mockedGetScenario.mockResolvedValueOnce(
      makeScenario({
        payload: {
          tenureMonths: 36,
          mileageBand: "standard",
          downpayment: "40000.00",
          comparison: makeComparisonResult(),
          tco: makeTcoReport(),
          scoring: null,
        },
      }),
    );

    renderPage();

    expect(await screen.findByText("TCO Breakdown & Depreciation")).toBeInTheDocument();
    expect(screen.getByText("RM 612,400.00")).toBeInTheDocument();
    expect(screen.getByText("RM 452,400.00")).toBeInTheDocument();

    expect(mockedFetchTcoReport).not.toHaveBeenCalled();
  });

  // Live-walkthrough finding (2026-10-05): a scenario saved before Batch
  // 6C added risk_radar/radar_unavailable/cumulative_cash_flow/
  // contract_checklist/risk_alerts has NONE of those keys in its stored
  // payload at all (not null, not []) - this previously crashed the
  // whole page (tripped the ErrorBoundary) when SavedScenarioPage
  // rendered that old report straight into TcoReportView. Built via
  // object destructuring (not just setting the fields to undefined) so
  // this fixture genuinely lacks the keys, matching exactly what a
  // JSON-parsed pre-6C database row looks like.
  function makePre6cTcoReport(): TcoReport {
    const {
      risk_radar: _risk_radar,
      radar_unavailable: _radar_unavailable,
      cumulative_cash_flow: _cumulative_cash_flow,
      contract_checklist: _contract_checklist,
      risk_alerts: _risk_alerts,
      ...rest
    } = makeTcoReport();
    return rest as TcoReport;
  }

  it("renders a pre-Batch-6C saved TCO report without crashing, with the new sections omitted/empty", async () => {
    mockedGetScenario.mockResolvedValueOnce(
      makeScenario({
        payload: {
          tenureMonths: 36,
          mileageBand: "standard",
          downpayment: "40000.00",
          comparison: makeComparisonResult(),
          tco: makePre6cTcoReport(),
          scoring: null,
        },
      }),
    );

    renderPage();

    // The pre-existing fields still render fine...
    expect(await screen.findByText("TCO Breakdown & Depreciation")).toBeInTheDocument();
    expect(screen.getByText("RM 612,400.00")).toBeInTheDocument();
    // ...and nothing throws/trips the ErrorBoundary over the missing
    // Batch 6C fields: RiskAlertsCard renders nothing (no alerts key),
    // ContractChecklistCard falls back to its "not configured" empty
    // state (no contract_checklist key, same as an explicit null).
    expect(screen.queryByText("Risk alerts")).not.toBeInTheDocument();
    expect(screen.getByText("Contract terms not yet configured for this brand")).toBeInTheDocument();
    expect(screen.getByText("3-axis risk comparison")).toBeInTheDocument();
    expect(screen.getByText("Cumulative cash flow")).toBeInTheDocument();
  });

  it("renders the recommendation section from the stored payload when present", async () => {
    mockedGetScenario.mockResolvedValueOnce(
      makeScenario({
        payload: {
          tenureMonths: 36,
          mileageBand: "standard",
          downpayment: "40000.00",
          comparison: makeComparisonResult(),
          tco: null,
          scoring: makeScoringResult(),
        },
      }),
    );

    renderPage();

    expect(await screen.findByText("AI Recommendation")).toBeInTheDocument();
    expect(screen.getByText(/Subscription best matches/i)).toBeInTheDocument();
    // Redesign UI-3: "Recommended" is on the best-match card in the AI section AND, from the
    // same saved result, on the Subscription card in Financing Pathways (it was only the former).
    const aiSection = screen.getByText("AI Recommendation").closest("section")!;
    expect(within(aiSection).getByText("Recommended")).toBeInTheDocument();
    expect(screen.getAllByText("Recommended")).toHaveLength(2);
    expect(within(screen.getByRole("article", { name: "Subscription" })).getByText("Recommended")).toBeInTheDocument();

    expect(mockedFetchScoring).not.toHaveBeenCalled();
  });

  // --- Run 1 fix batch 2 (G6): the banner says who calculated the figures ------

  it("says a server-built snapshot was calculated by FlexiDriveMy", async () => {
    mockedGetScenario.mockResolvedValueOnce(
      makeScenario({
        payload: { ...makeScenario().payload, snapshotVersion: 2, builtBy: "server" },
      }),
    );

    renderPage();

    expect(
      await screen.findByText(
        /^Saved on .+\. These figures were calculated by FlexiDriveMy when you saved and are kept unchanged, even if rates or prices change later\.$/,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/exactly what was saved/)).not.toBeInTheDocument();
    expect(screen.queryByText(/earlier version/)).not.toBeInTheDocument();
  });

  it("says an older row was saved by an earlier version, without claiming who calculated it", async () => {
    mockedGetScenario.mockResolvedValueOnce(makeScenario()); // no snapshotVersion

    renderPage();

    expect(
      await screen.findByText(
        /^Saved on .+ by an earlier version of FlexiDriveMy\. Figures are kept unchanged from that time\.$/,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/calculated by FlexiDriveMy/)).not.toBeInTheDocument();
    expect(screen.queryByText(/exactly what was saved/)).not.toBeInTheDocument();
  });

  // --- Run 1 fix batch 3: the running-cost rows show the API's basis and NCD ----

  it("shows the API's basis lines and the before-NCD note when no NCD was applied", async () => {
    mockedGetScenario.mockResolvedValueOnce(
      makeScenario({
        payload: {
          ...makeScenario().payload,
          tco: makeTcoReport({
            ncd_percent: "0.00",
            operating_cost_basis: {
              road_tax: "1,984 cc petrol, non-saloon - JPJ cc schedule",
              insurance: "1.8% of RM 469,000.00",
              maintenance: "1.0% of price, capped at RM 8,000 (floor RM 1,200)",
            },
          }),
        },
      }),
    );

    renderPage();

    expect(await screen.findByText("1,984 cc petrol, non-saloon - JPJ cc schedule")).toBeInTheDocument();
    expect(screen.getByText("1.0% of price, capped at RM 8,000 (floor RM 1,200)")).toBeInTheDocument();
    expect(
      screen.getByText("Insurance shown before No-Claim Discount. Add your NCD in Financial Profile."),
    ).toBeInTheDocument();
  });

  it("shows the NCD in the insurance basis and no before-NCD note when one was applied", async () => {
    mockedGetScenario.mockResolvedValueOnce(
      makeScenario({
        payload: {
          ...makeScenario().payload,
          tco: makeTcoReport({
            ncd_percent: "55.00",
            insurance_annual: "2152.98",
            operating_cost_basis: {
              road_tax: "1,998 cc petrol, saloon - JPJ cc schedule",
              insurance: "1.8% of RM 265,800.00, less 55% NCD",
              maintenance: "1.0% of price (floor RM 1,200)",
            },
          }),
        },
      }),
    );

    renderPage();

    expect(await screen.findByText("1.8% of RM 265,800.00, less 55% NCD")).toBeInTheDocument();
    expect(screen.getByText("RM 2,152.98 / yr")).toBeInTheDocument();
    expect(screen.queryByText(/before No-Claim Discount/)).not.toBeInTheDocument();
  });

  // --- Run 3 fix batch 6: the mileage bands were recalibrated -----------------------

  it("opens a snapshot saved before the band recalibration with its own saved mileage wording", async () => {
    const comparison = makeComparisonResult();
    comparison.subscription = {
      ...comparison.subscription!,
      included_km_per_year: PRE_BATCH6_STANDARD_INCLUDED_KM,
      mileage_note: PRE_BATCH6_STANDARD_MILEAGE_NOTE,
    };
    const { forecast_cap_note: _absent, ...oldTco } = makeTcoReport({ forecast_cap_note: null });
    mockedGetScenario.mockResolvedValueOnce(
      makeScenario({
        payload: { ...makeScenario().payload, snapshotVersion: 2, builtBy: "server", comparison, tco: oldTco as TcoReport },
      }),
    );

    const { container } = renderPage();

    expect(await screen.findByText(PRE_BATCH6_STANDARD_MILEAGE_NOTE)).toBeInTheDocument();
    expect(screen.getByText("TCO Breakdown & Depreciation")).toBeInTheDocument();
    expect(screen.queryByText(/capped at the mileage/)).not.toBeInTheDocument();
    expect(container.textContent).not.toContain("undefined");
    expect(mockedFetchComparison).not.toHaveBeenCalled();
    expect(mockedFetchTcoReport).not.toHaveBeenCalled();
  });

  it("shows why the TCO is missing where the TCO section would be", async () => {
    const reason =
      "Hire Purchase and GFV aren't available for this car yet because its financing rate hasn't been set up.";
    mockedGetScenario.mockResolvedValueOnce(
      makeScenario({
        payload: { ...makeScenario().payload, snapshotVersion: 2, builtBy: "server", tcoUnavailableReason: reason },
      }),
    );

    renderPage();

    expect(await screen.findByText("TCO Breakdown & Depreciation")).toBeInTheDocument();
    expect(screen.getByText(reason)).toBeInTheDocument();
  });

  // --- Redesign UI-4: the header ------------------------------------------------------

  it("shows a slim 'figures frozen' badge with the full sentence folded beside it", async () => {
    mockedGetScenario.mockResolvedValueOnce(
      makeScenario({
        updated_at: "2026-03-01T00:00:00Z",
        payload: { ...makeScenario().payload, snapshotVersion: 2, builtBy: "server" },
      }),
    );

    renderPage();

    const badge = await screen.findByText("Saved 1 Mar 2026 · figures frozen");
    expect(badge).toHaveAttribute("data-tone", "neutral");
    const sentence = screen.getByText(/^Saved on 1 Mar 2026\. These figures were calculated by FlexiDriveMy/);
    expect(sentence.closest("details")).not.toBeNull();
    expect(sentence.closest("details")?.querySelector("summary")).toHaveTextContent("About these figures");
  });

  it("says 'earlier version' on the badge for an older snapshot", async () => {
    mockedGetScenario.mockResolvedValueOnce(makeScenario({ updated_at: "2026-03-01T00:00:00Z" }));

    renderPage();

    expect(await screen.findByText("Saved 1 Mar 2026 · earlier version")).toHaveAttribute("data-tone", "neutral");
    expect(screen.queryByText(/figures frozen/)).not.toBeInTheDocument();
  });

  it("puts the title in the page header with a back link and the car, downpayment and tenure", async () => {
    mockedGetScenario.mockResolvedValueOnce(makeScenario());

    renderPage();

    const scenario = makeScenario();
    const heading = await screen.findByRole("heading", { level: 1, name: scenario.title });
    const header = heading.closest("header") as HTMLElement;
    expect(within(header).getByRole("link", { name: "Back to My Comparisons" })).toHaveAttribute("href", "/scenarios");
    expect(within(header).getByText("Honda City V · RM 40,000.00 downpayment · 36 months")).toBeInTheDocument();
  });

  it("shows '–' in the header for a downpayment or tenure an older snapshot lacks", async () => {
    const scenario = makeScenario();
    mockedGetScenario.mockResolvedValueOnce(
      makeScenario({ payload: { ...scenario.payload, downpayment: undefined, tenureMonths: undefined } as never }),
    );

    renderPage();

    expect(await screen.findByText(`${scenario.vehicle_label} · – downpayment · – months`)).toBeInTheDocument();
  });

  it("gives each saved section's heading the compare page's tab icon", async () => {
    mockedGetScenario.mockResolvedValueOnce(makeScenario());

    renderPage();

    const heading = await screen.findByRole("heading", { level: 2, name: "Financing Pathways" });
    expect(heading.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  // --- FX-1 (X5): Delete on the saved page --------------------------------------------------------

  function renderWithList() {
    return render(
      <MemoryRouter initialEntries={["/scenarios/1"]}>
        <Routes>
          <Route path="/scenarios/:id" element={<SavedScenarioPage />} />
          <Route path="/scenarios" element={<p>My comparisons list</p>} />
        </Routes>
      </MemoryRouter>,
    );
  }

  it("deletes after the app's confirm dialog and goes to My Comparisons", async () => {
    mockedGetScenario.mockResolvedValueOnce(makeScenario());
    mockedDeleteScenario.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();

    renderWithList();
    const del = await screen.findByRole("button", { name: "Delete" });
    expect(del).toHaveAttribute("data-variant", "danger-quiet");
    await user.click(del);

    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByText("Delete this saved comparison?")).toBeInTheDocument();
    expect(within(dialog).getByText("This cannot be undone.")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    expect(await screen.findByText("My comparisons list")).toBeInTheDocument();
    expect(mockedDeleteScenario).toHaveBeenCalledWith(1);
  });

  it("keeps the comparison when the dialog is cancelled or closed with Escape", async () => {
    mockedGetScenario.mockResolvedValueOnce(makeScenario());
    const user = userEvent.setup();

    renderWithList();
    await user.click(await screen.findByRole("button", { name: "Delete" }));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel" }));
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.getByText("Honda City comparison")).toBeInTheDocument();
    expect(mockedDeleteScenario).not.toHaveBeenCalled();
  });

  it("says so in plain words when the delete fails, and stays on the page", async () => {
    mockedGetScenario.mockResolvedValueOnce(makeScenario());
    mockedDeleteScenario.mockRejectedValueOnce(new Error("network"));
    const user = userEvent.setup();

    renderWithList();
    await user.click(await screen.findByRole("button", { name: "Delete" }));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not delete this comparison. Please try again.");
    expect(screen.getByText("Honda City comparison")).toBeInTheDocument();
  });
});
