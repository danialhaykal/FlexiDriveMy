import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AdminPolicyPage } from "./AdminPolicyPage";
import {
  archiveInterestRate,
  createInterestRate,
  createSubscriptionPlan,
  fetchContractPenaltyRules,
  fetchInterestRates,
  fetchMCDAWeights,
  fetchOperatingCosts,
  fetchResidualEstimates,
  fetchResidualValueMatrix,
  fetchSubscriptionEstimates,
  fetchSubscriptionPlans,
  updateInterestRate,
} from "../api/policy";
import { fetchAdminBrands, fetchAdminVehicles } from "../api/adminFleet";
import type {
  InterestRate,
  MCDACriteriaWeight,
  OperatingCostsResponse,
  ResidualEstimatesResponse,
  SubscriptionEstimatesResponse,
} from "../types/policy";
import type { AdminBrand } from "../types/adminFleet";
import { fetchMileageBands } from "../api/mileageBands";
import { resetMileageBandOptionsCache } from "../hooks/useMileageBandOptions";
import { API_MILEAGE_BANDS, bandLabel } from "../test/mileageBandsFixture";

vi.mock("../api/policy", () => ({
  fetchInterestRates: vi.fn(),
  createInterestRate: vi.fn(),
  updateInterestRate: vi.fn(),
  archiveInterestRate: vi.fn(),
  fetchResidualValueMatrix: vi.fn(),
  createResidualValueMatrixEntry: vi.fn(),
  updateResidualValueMatrixEntry: vi.fn(),
  archiveResidualValueMatrixEntry: vi.fn(),
  fetchMCDAWeights: vi.fn(),
  updateMCDAWeights: vi.fn(),
  fetchOperatingCosts: vi.fn(),
  fetchResidualEstimates: vi.fn(),
  fetchSubscriptionEstimates: vi.fn(),
  fetchSubscriptionPlans: vi.fn(),
  createSubscriptionPlan: vi.fn(),
  updateSubscriptionPlan: vi.fn(),
  archiveSubscriptionPlan: vi.fn(),
  fetchContractPenaltyRules: vi.fn(),
  createContractPenaltyRule: vi.fn(),
  updateContractPenaltyRule: vi.fn(),
  archiveContractPenaltyRule: vi.fn(),
}));

vi.mock("../api/mileageBands", () => ({ fetchMileageBands: vi.fn() }));
vi.mock("../api/adminFleet", () => ({
  fetchAdminBrands: vi.fn(),
  fetchAdminVehicles: vi.fn(),
}));

const mockedFetchInterestRates = vi.mocked(fetchInterestRates);
const mockedCreateInterestRate = vi.mocked(createInterestRate);
const mockedUpdateInterestRate = vi.mocked(updateInterestRate);
const mockedFetchResidualValueMatrix = vi.mocked(fetchResidualValueMatrix);
const mockedFetchMCDAWeights = vi.mocked(fetchMCDAWeights);
const mockedFetchOperatingCosts = vi.mocked(fetchOperatingCosts);
const mockedFetchResidualEstimates = vi.mocked(fetchResidualEstimates);
const mockedFetchSubscriptionEstimates = vi.mocked(fetchSubscriptionEstimates);
const mockedCreateSubscriptionPlan = vi.mocked(createSubscriptionPlan);
const mockedFetchSubscriptionPlans = vi.mocked(fetchSubscriptionPlans);
const mockedFetchContractPenaltyRules = vi.mocked(fetchContractPenaltyRules);
const mockedFetchAdminBrands = vi.mocked(fetchAdminBrands);
const mockedFetchAdminVehicles = vi.mocked(fetchAdminVehicles);

const brand: AdminBrand = {
  id: 1,
  name: "Toyota",
  tier_code: "1",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const interestRate: InterestRate = {
  id: 1,
  brand: 1,
  brand_name: "Toyota",
  rate_percent: "3.5000",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const mcdaWeights: MCDACriteriaWeight[] = [
  { id: 1, criterion: "upfront_cash_preservation", default_weight: "0.4000", is_active: true, updated_at: "2026-01-01T00:00:00Z" },
  { id: 2, criterion: "maintenance_protection", default_weight: "0.3000", is_active: true, updated_at: "2026-01-01T00:00:00Z" },
  { id: 3, criterion: "ownership_equity", default_weight: "0.3000", is_active: true, updated_at: "2026-01-01T00:00:00Z" },
];

const operatingCosts: OperatingCostsResponse = {
  road_tax_cc_bands: [
    {
      id: 1, vehicle_class: "saloon", vehicle_class_label: "Saloon", fuel_schedule: "petrol", min_cc: 0,
      max_cc: 1000, base_amount: "20.00", threshold_cc: 0, per_cc_rate: "0.00",
      source_note: "JPJ private-car schedule, Peninsular Malaysia.", effective_from: "2007-01-01", is_active: true,
    },
    {
      id: 2, vehicle_class: "saloon", vehicle_class_label: "Saloon", fuel_schedule: "petrol", min_cc: 1801,
      max_cc: 2000, base_amount: "280.00", threshold_cc: 1800, per_cc_rate: "0.50",
      source_note: "JPJ private-car schedule, Peninsular Malaysia.", effective_from: "2007-01-01", is_active: true,
    },
    {
      id: 4, vehicle_class: "non_saloon", vehicle_class_label: "Non-saloon", fuel_schedule: "petrol", min_cc: 1801,
      max_cc: 2000, base_amount: "360.00", threshold_cc: 1800, per_cc_rate: "0.40",
      source_note: "JPJ non-saloon table - StashAway 2026. Check MyJPJ for the exact class.",
      effective_from: "2007-01-01", is_active: true,
    },
  ],
  archived_diesel_cc_bands: [
    {
      id: 3, vehicle_class: "saloon", vehicle_class_label: "Saloon", fuel_schedule: "diesel", min_cc: 1601,
      max_cc: 1800, base_amount: "400.00", threshold_cc: 1600, per_cc_rate: "0.80",
      source_note: "JPJ diesel schedule. SINGLE SOURCE - verify before relying on it.",
      effective_from: "2007-01-01", is_active: false,
    },
  ],
  ev_road_tax_groups: [
    {
      id: 1, label: "C", min_kw: "210.100", max_kw: "310.000", base_amount: "305.00", base_until_kw: "220.00",
      increment_per_10kw: "30.00", source_note: "JPJ EV kW groups, from 1 Jan 2026.", effective_from: "2026-01-01",
    },
    {
      id: 2, label: "K", min_kw: "1010.100", max_kw: null, base_amount: "20000.00", base_until_kw: null,
      increment_per_10kw: "0.00", source_note: "JPJ EV kW groups, from 1 Jan 2026.", effective_from: "2026-01-01",
    },
  ],
  cost_rates: [
    {
      id: 1, powertrain: "petrol", powertrain_label: "Petrol", insurance_rate_percent: "2.6000",
      maintenance_rate_percent: "1.0000", maintenance_floor_annual: "1200.00", maintenance_cap_annual: "8000.00",
      source_note: "Planning estimate - edit in admin.", effective_from: "2026-10-07",
    },
    {
      id: 2, powertrain: "bev", powertrain_label: "Battery electric (BEV)", insurance_rate_percent: "2.3000",
      maintenance_rate_percent: "0.7000", maintenance_floor_annual: "1200.00", maintenance_cap_annual: null,
      source_note: "Planning estimate - edit in admin.", effective_from: "2026-10-07",
    },
  ],
};

const PLANNING_NOTE = "Planning estimate - directional, edit in admin. Real GFV residuals are set by the lender.";
const residualEstimates: ResidualEstimatesResponse = {
  baselines: [
    { id: 1, tenure_months: 36, mileage_band: "low", ratio: "0.5500", source_note: PLANNING_NOTE, effective_from: "2026-10-07" },
    { id: 2, tenure_months: 36, mileage_band: "standard", ratio: "0.5000", source_note: PLANNING_NOTE, effective_from: "2026-10-07" },
    { id: 3, tenure_months: 48, mileage_band: "standard", ratio: "0.4200", source_note: PLANNING_NOTE, effective_from: "2026-10-07" },
  ],
  adjustments: [
    {
      id: 1, brand: 1, brand_name: "Toyota", powertrain: "", powertrain_label: "", delta_points: "0.0600",
      source_note: `${PLANNING_NOTE} Toyota is known to hold its value well.`, effective_from: "2026-10-07",
    },
    {
      id: 2, brand: null, brand_name: null, powertrain: "bev", powertrain_label: "Battery electric (BEV)",
      delta_points: "-0.0800", source_note: `${PLANNING_NOTE} Electric cars depreciate faster.`, effective_from: "2026-10-07",
    },
  ],
};

const subscriptionEstimates: SubscriptionEstimatesResponse = {
  policies: [
    {
      id: 1, min_tenure_months: 12, max_tenure_months: 36, funding_rate_percent: "4.5000", margin_percent: "12.0000",
      deposit_months: "2.00", low_km_cap: API_MILEAGE_BANDS[0].upper_km, standard_km_cap: API_MILEAGE_BANDS[1].upper_km, high_km_cap: API_MILEAGE_BANDS[2].upper_km, very_high_km_cap: API_MILEAGE_BANDS[3].upper_km ?? 0,
      source_note: "Planning estimate - edit in admin. Real subscription terms vary by provider.",
      effective_from: "2026-10-07",
    },
  ],
};

function setupDefaultMocks() {
  resetMileageBandOptionsCache();
  vi.mocked(fetchMileageBands).mockResolvedValue(API_MILEAGE_BANDS);
  mockedFetchAdminBrands.mockResolvedValue([brand]);
  mockedFetchAdminVehicles.mockResolvedValue([]);
  mockedFetchInterestRates.mockResolvedValue([interestRate]);
  mockedFetchResidualValueMatrix.mockResolvedValue([]);
  mockedFetchMCDAWeights.mockResolvedValue(mcdaWeights);
  mockedFetchOperatingCosts.mockResolvedValue(operatingCosts);
  mockedFetchResidualEstimates.mockResolvedValue(residualEstimates);
  mockedFetchSubscriptionEstimates.mockResolvedValue(subscriptionEstimates);
  mockedFetchSubscriptionPlans.mockResolvedValue([]);
  mockedFetchContractPenaltyRules.mockResolvedValue([]);
}

describe("AdminPolicyPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    setupDefaultMocks();
  });

  it("shows the Interest Rates tab by default, with its list loaded", async () => {
    render(<AdminPolicyPage />);

    expect(await screen.findByText("3.50% flat p.a.")).toBeInTheDocument();
  });

  // --- Run 1 fix batch 5: UC011's button label and the edit-conflict check ------

  it("saves an edit with 'Apply Policy Update', sending the updated_at it loaded", async () => {
    mockedUpdateInterestRate.mockResolvedValueOnce({ ...interestRate, rate_percent: "2.9000" });
    const user = userEvent.setup();
    const { container } = render(<AdminPolicyPage />);
    await screen.findByText("3.50% flat p.a.");

    // Redesign UI-6a: Edit is in the row's menu.
    await user.click(screen.getByRole("button", { name: "Actions for Toyota interest rate" }));
    await user.click(await screen.findByRole("menuitem", { name: "Edit" }));
    const rate = screen.getByLabelText("Flat rate (% p.a.)");
    await user.clear(rate);
    await user.type(rate, "2.9000");
    await user.click(screen.getByRole("button", { name: "Apply Policy Update" }));

    expect(mockedUpdateInterestRate).toHaveBeenCalledWith(1, {
      brand: 1,
      rate_percent: "2.9000",
      updated_at: "2026-01-01T00:00:00Z",
    });
    expect(container.textContent).not.toContain("Save Changes");
  });

  it("on a 409 says someone else changed it and keeps the typed value", async () => {
    mockedUpdateInterestRate.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 409,
        data: { detail: "This record was changed by someone else. Reload to see the latest version." },
      },
    });
    const user = userEvent.setup();
    render(<AdminPolicyPage />);
    await screen.findByText("3.50% flat p.a.");

    // Redesign UI-6a: Edit is in the row's menu.
    await user.click(screen.getByRole("button", { name: "Actions for Toyota interest rate" }));
    await user.click(await screen.findByRole("menuitem", { name: "Edit" }));
    const rate = screen.getByLabelText("Flat rate (% p.a.)");
    await user.clear(rate);
    await user.type(rate, "2.9000");
    await user.click(screen.getByRole("button", { name: "Apply Policy Update" }));

    expect(
      await screen.findByText("This record was changed by someone else. Reload to see the latest version."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Flat rate (% p.a.)")).toHaveValue("2.9000");
  });

  it("preserves valid fields and shows the exact server message when adding an interest rate fails", async () => {
    mockedCreateInterestRate.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 400,
        data: { rate_percent: ["Interest rate input exceeds acceptable limits (0.01% – 15.00%)."] },
      },
    });
    const user = userEvent.setup();

    render(<AdminPolicyPage />);
    await screen.findByText("3.50% flat p.a.");

    await user.click(screen.getByRole("button", { name: "Add Interest Rate" }));
    await user.selectOptions(screen.getByLabelText("Brand"), "1");
    await user.type(screen.getByLabelText("Flat rate (% p.a.)"), "20.00");
    await user.click(screen.getByRole("button", { name: "Create" }));

    expect(
      await screen.findByText("Interest rate input exceeds acceptable limits (0.01% – 15.00%)."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Flat rate (% p.a.)")).toHaveValue("20.00");
  });

  it("switches to the MCDA Weights tab and shows a running sum of the three criteria", async () => {
    const user = userEvent.setup();
    render(<AdminPolicyPage />);
    await screen.findByText("3.50% flat p.a.");

    await user.click(screen.getByRole("tab", { name: "Default Priority Weights" }));

    // FX-3 (X13): as a percentage (was "Running sum: 1.0000").
    expect(await screen.findByText("Running sum: 100%")).toBeInTheDocument();
  });

  it("switches to the Contract Penalty Rules tab and lists its own section", async () => {
    mockedFetchContractPenaltyRules.mockResolvedValueOnce([
      {
        id: 1,
        brand: 1,
        brand_name: "Toyota",
        excess_mileage_charge_per_km: "0.50",
        early_termination_months: "6.00",
        wear_tear_tolerance_description: "Normal wear and tear accepted.",
        source_note: "",
        is_active: true,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      },
    ]);
    const user = userEvent.setup();
    render(<AdminPolicyPage />);
    await screen.findByText("3.50% flat p.a.");

    await user.click(screen.getByRole("tab", { name: "Contract Penalty Rules" }));

    const panel = await screen.findByRole("tabpanel");
    expect(within(panel).getByText("0.50")).toBeInTheDocument();
    expect(within(panel).getByText("6.00")).toBeInTheDocument();
  });

  // Same rule as AdminFleetPage's vehicle form: Add offers active brands
  // only; Edit also keeps the row's own brand even after it was archived.
  const archivedBrand: AdminBrand = {
    id: 2,
    name: "Honda",
    tier_code: "4",
    is_active: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
  const timestamps = { is_active: true, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" };

  const brandSections = [
    {
      section: "Interest Rate",
      tab: null,
      addButton: "Add Interest Rate",
      mockArchivedBrandRow: () =>
        mockedFetchInterestRates.mockResolvedValue([
          interestRate,
          { ...interestRate, ...timestamps, id: 2, brand: 2, brand_name: "Honda", rate_percent: "4.0000" },
        ]),
    },
    {
      section: "Residual Override",
      tab: "Residual Overrides",
      addButton: "Add Residual Override",
      mockArchivedBrandRow: () =>
        mockedFetchResidualValueMatrix.mockResolvedValue([
          {
            ...timestamps,
            id: 1,
            brand: 2,
            brand_name: "Honda",
            tenure_months: 36,
            mileage_band: "standard",
            residual_value_ratio: "0.5000",
          },
        ]),
    },
    {
      section: "Contract Penalty Rule",
      tab: "Contract Penalty Rules",
      addButton: "Add Contract Penalty Rule",
      mockArchivedBrandRow: () =>
        mockedFetchContractPenaltyRules.mockResolvedValue([
          {
            ...timestamps,
            id: 1,
            brand: 2,
            brand_name: "Honda",
            excess_mileage_charge_per_km: "0.50",
            early_termination_months: "3.00",
            wear_tear_tolerance_description: "Normal wear and tear accepted.",
            source_note: "",
          },
        ]),
    },
  ];

  async function openSection(user: ReturnType<typeof userEvent.setup>, tab: string | null) {
    render(<AdminPolicyPage />);
    await screen.findByText("3.50% flat p.a.");
    if (tab) await user.click(screen.getByRole("tab", { name: tab }));
    return screen.findByRole("tabpanel");
  }

  function brandOptionLabels(scope: HTMLElement) {
    const select = within(scope).getByLabelText("Brand") as HTMLSelectElement;
    return { select, labels: Array.from(select.options).map((option) => option.textContent) };
  }

  it.each(brandSections)("excludes archived brands from a new $section's Brand options", async ({ tab, addButton }) => {
    mockedFetchAdminBrands.mockResolvedValue([brand, archivedBrand]);
    const user = userEvent.setup();

    const panel = await openSection(user, tab);
    await user.click(within(panel).getByRole("button", { name: addButton }));

    const { labels } = brandOptionLabels(panel);
    expect(labels).toContain("Toyota");
    expect(labels).not.toContain("Honda (archived)");
    expect(labels).not.toContain("Honda");
  });

  it.each(brandSections)(
    "still offers an edited $section's own brand after it was archived",
    async ({ tab, mockArchivedBrandRow }) => {
      mockedFetchAdminBrands.mockResolvedValue([brand, archivedBrand]);
      mockArchivedBrandRow();
      const user = userEvent.setup();

      const panel = await openSection(user, tab);
      const row = (await within(panel).findByText("Honda")).closest("tr");
      if (!row) throw new Error("archived-brand row not found");
      // Redesign UI-6a: Edit is in the row's menu.
      await user.click(within(row).getByRole("button", { name: /^Actions for Honda/ }));
      await user.click(await screen.findByRole("menuitem", { name: "Edit" }));

      const { select, labels } = brandOptionLabels(panel);
      expect(labels).toContain("Honda (archived)");
      expect(select).toHaveValue("2");
      expect(labels).toContain("Toyota");
    },
  );

  // --- Audit batch 2: one operating-cost engine ---------------------------

  it("replaces the old Operating Cost Bands tab with a read-only Operating Costs tab", async () => {
    const user = userEvent.setup();
    render(<AdminPolicyPage />);
    await screen.findByText("3.50% flat p.a.");

    expect(screen.queryByRole("tab", { name: "Operating Cost Bands" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Operating Costs" }));

    const panel = await screen.findByRole("tabpanel");
    expect(
      await within(panel).findByText(
        "Road tax follows JPJ; insurance and maintenance are percentage estimates. Edit in Django admin.",
      ),
    ).toBeInTheDocument();
    // Road tax by cc: a flat band and a progressive one, shown as returned.
    expect(within(panel).getByText("Flat")).toBeInTheDocument();
    expect(within(panel).getByText("RM 0.50 per cc above 1800")).toBeInTheDocument();
    // Run 1 fix batch 3: the saloon and non-saloon tables side by side, each with its own bands.
    expect(within(panel).getByText("Road tax by engine capacity (cc) - saloon")).toBeInTheDocument();
    expect(within(panel).getByText("Road tax by engine capacity (cc) - non-saloon")).toBeInTheDocument();
    expect(within(panel).getByText("RM 0.40 per cc above 1800")).toBeInTheDocument();
    expect(
      within(panel).getByText("Source: JPJ non-saloon table - StashAway 2026. Check MyJPJ for the exact class."),
    ).toBeInTheDocument();
    expect(within(panel).queryByText("Road tax by engine capacity (cc) - diesel")).not.toBeInTheDocument();
    // The old diesel rows: shown read-only, labelled archived and not used.
    expect(within(panel).getByText("Archived: old diesel schedule (not used)")).toBeInTheDocument();
    expect(within(panel).getByText("Archived")).toBeInTheDocument();
    expect(within(panel).getByText("RM 0.80 per cc above 1600")).toBeInTheDocument();
    expect(
      within(panel).getByText("Source: JPJ diesel schedule. SINGLE SOURCE - verify before relying on it."),
    ).toBeInTheDocument();
    // The maintenance cap column: the API's figure, or "No cap" when it has none.
    expect(within(panel).getByText("Maintenance cap")).toBeInTheDocument();
    expect(within(panel).getByText("RM 8,000.00")).toBeInTheDocument();
    expect(within(panel).getByText("No cap")).toBeInTheDocument();
    // EV groups, including the open-ended fixed-amount group.
    // FX-3 (X13): one readable range (was "1010.100" / "and above").
    expect(within(panel).getByText("Above 210 kW to 310 kW")).toBeInTheDocument();
    expect(within(panel).getByText("Above 1,010 kW")).toBeInTheDocument();
    expect(within(panel).queryByText("and above")).not.toBeInTheDocument();
    expect(within(panel).getByText("Fixed amount")).toBeInTheDocument();
    // Insurance/maintenance percentages by powertrain.
    expect(within(panel).getByText("Petrol")).toBeInTheDocument();
    // Redesign UI-6a: 2 dp with its unit (the API's "2.6000").
    expect(within(panel).getByText("2.60%")).toBeInTheDocument();
    // Provenance: where each rate came from (duplicates collapsed), and when it took effect.
    expect(within(panel).getAllByText("Source: JPJ private-car schedule, Peninsular Malaysia.")).toHaveLength(1);
    expect(within(panel).getByText("Source: JPJ EV kW groups, from 1 Jan 2026.")).toBeInTheDocument();
    expect(within(panel).getByText("Source: Planning estimate - edit in admin.")).toBeInTheDocument();
    // FX-3 (X13): the one admin date format (was "2007-01-01").
    expect(within(panel).getAllByText("1 Jan 2007").length).toBeGreaterThan(0);
    // Read-only: no add/edit/archive controls.
    expect(within(panel).queryByRole("button")).not.toBeInTheDocument();
  });

  // --- Audit batch 4: residuals are estimated; a matrix row is an override ----

  it("renames the matrix tab to Residual Overrides and explains that it is optional", async () => {
    const user = userEvent.setup();
    render(<AdminPolicyPage />);
    await screen.findByText("3.50% flat p.a.");

    expect(screen.queryByRole("tab", { name: "Residual Value Matrix" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Residual Overrides" }));

    const panel = await screen.findByRole("tabpanel");
    expect(
      await within(panel).findByText(
        "Optional. Leave empty and the app estimates each car's residual from the baseline and adjustments.",
      ),
    ).toBeInTheDocument();
    expect(within(panel).getByText("No residual overrides - the estimates are used")).toBeInTheDocument();
  });

  it("adds a read-only Residual Estimates tab showing the baseline grid and the adjustments with their notes", async () => {
    const user = userEvent.setup();
    render(<AdminPolicyPage />);
    await screen.findByText("3.50% flat p.a.");

    await user.click(screen.getByRole("tab", { name: "Residual Estimates" }));

    const panel = await screen.findByRole("tabpanel");
    expect(await within(panel).findByText("Baseline: share of price retained")).toBeInTheDocument();
    // grid cells: the API's ratios shown as percentages (redesign UI-6a; were "0.5500" /
    // "0.4200"), and a missing cell shown as a dash
    expect(within(panel).getByText("55.00%")).toBeInTheDocument();
    expect(within(panel).getByText("42.00%")).toBeInTheDocument();
    expect(within(panel).getAllByText("-").length).toBeGreaterThan(0);
    // adjustments: a brand row and a powertrain row, shown as signed points (redesign
    // UI-6a; were "0.0600" / "-0.0800")
    expect(within(panel).getByText("Toyota")).toBeInTheDocument();
    expect(within(panel).getByText("+6.00 pts")).toBeInTheDocument();
    expect(within(panel).getByText("Battery electric (BEV)")).toBeInTheDocument();
    expect(within(panel).getByText("-8.00 pts")).toBeInTheDocument();
    // every row says plainly that it is a planning assumption
    // FX-3 (X13): the shared source once under each table (was once in total, the adjustments' notes each
    // repeating it in full); what a row adds is in its Note column.
    expect(within(panel).getAllByText(`Source: ${PLANNING_NOTE}`)).toHaveLength(2);
    expect(within(panel).getByText("Toyota is known to hold its value well.")).toBeInTheDocument();
    expect(within(panel).getByText("Electric cars depreciate faster.")).toBeInTheDocument();
    expect(within(panel).getAllByText(/planning assumptions, not market data/).length).toBe(1);
    // read-only
    expect(within(panel).queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows the default contract rule as 'Default (all brands)' and offers it in the brand dropdown", async () => {
    mockedFetchContractPenaltyRules.mockResolvedValue([
      {
        id: 9, brand: null, brand_name: null, excess_mileage_charge_per_km: "0.50", early_termination_months: "3.00",
        wear_tear_tolerance_description: "Normal wear accepted.", source_note: "Planning estimate",
        is_active: true, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
      },
    ]);
    const user = userEvent.setup();
    render(<AdminPolicyPage />);
    await screen.findByText("3.50% flat p.a.");

    await user.click(screen.getByRole("tab", { name: "Contract Penalty Rules" }));
    const panel = await screen.findByRole("tabpanel");

    expect(await within(panel).findByText("Default (all brands)")).toBeInTheDocument();
    expect(within(panel).getByText("3.00")).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Add Contract Penalty Rule" }));
    const labels = Array.from((within(panel).getByLabelText("Brand") as HTMLSelectElement).options).map((o) => o.textContent);
    expect(labels[0]).toBe("Default rule (all brands)");
    expect(within(panel).getByLabelText("Subscription early-return fee (months of fee)")).toBeInTheDocument();
    expect(within(panel).queryByLabelText("Early termination fee (RM)")).not.toBeInTheDocument();
  });

  // --- Audit batch 5: Subscription is estimated; a plan is a provider quote ----

  it("renames the Subscription Plans tab to Provider Quote Overrides and explains that it is optional", async () => {
    const user = userEvent.setup();
    render(<AdminPolicyPage />);
    await screen.findByText("3.50% flat p.a.");

    expect(screen.queryByRole("tab", { name: "Subscription Plans" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Provider Quote Overrides" }));

    const panel = await screen.findByRole("tabpanel");
    expect(
      await within(panel).findByText(
        "Optional. Leave a car without a plan and the app estimates its subscription fee from depreciation, funding, running costs and a margin. Add a plan only when you have a real provider quote.",
      ),
    ).toBeInTheDocument();
    expect(within(panel).getByText("No provider quotes - every fee is estimated")).toBeInTheDocument();
  });

  it("adds a read-only Subscription Estimates tab listing the policy values and its planning-estimate note", async () => {
    const user = userEvent.setup();
    render(<AdminPolicyPage />);
    await screen.findByText("3.50% flat p.a.");

    await user.click(screen.getByRole("tab", { name: "Subscription Estimates" }));

    const panel = await screen.findByRole("tabpanel");
    // Run 3 fix batch 5 (F-18): units and 2 dp (were "4.5000", "12.0000", "2.00", "40000").
    expect(await within(panel).findByText("4.50%")).toBeInTheDocument(); // funding rate
    expect(within(panel).getByText("12.00%")).toBeInTheDocument(); // margin
    expect(within(panel).getByText("2")).toBeInTheDocument(); // deposit months
    // Run 3 fix batch 6: every band with its included km, from the API (it used to show the very high band only).
    for (const band of API_MILEAGE_BANDS) expect(await within(panel).findByText(band.label)).toBeInTheDocument();
    expect(within(panel).getByText(`- includes ${(API_MILEAGE_BANDS[3].included_km_per_year ?? 0).toLocaleString("en-MY")} km/year`)).toBeInTheDocument();
    expect(
      within(panel).getByText("Source: Planning estimate - edit in admin. Real subscription terms vary by provider."),
    ).toBeInTheDocument();
    expect(within(panel).getByText(/planning assumptions, not provider data/)).toBeInTheDocument();
    expect(within(panel).queryByRole("button")).not.toBeInTheDocument();
  });

  // --- Audit batch 6: honest labels, no developer text -----------------------

  it("says plainly that the admin default priority weights are reference only and not applied to scoring", async () => {
    const user = userEvent.setup();
    render(<AdminPolicyPage />);
    await screen.findByText("3.50% flat p.a.");

    expect(screen.queryByRole("tab", { name: "MCDA Weights" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Default Priority Weights" }));

    const panel = await screen.findByRole("tabpanel");
    expect(
      await within(panel).findByText(
        "Reference defaults. A buyer's own three priority ratings decide the recommendation; these defaults are not applied to scoring yet.",
      ),
    ).toBeInTheDocument();
    // the sum-to-1.0 check and running total are unchanged (FX-3: shown as a percentage, was "1.0000")
    expect(within(panel).getByText("Running sum: 100%")).toBeInTheDocument();
  });

  it("shows no developer references (the project spec, use-case or batch codes) on any Policy Configuration tab", async () => {
    const user = userEvent.setup();
    const { container } = render(<AdminPolicyPage />);
    await screen.findByText("3.50% flat p.a.");
    const developerText = /CLAUDE|\bUC0\d\d\b|\bF0\d\d\b|\bsprint\b|\bTODO\b|QA audit|audit batch/i;

    const tabs = screen.getAllByRole("tab");
    expect(tabs.length).toBeGreaterThan(5);
    for (const tab of tabs) {
      await user.click(tab);
      const panel = await screen.findByRole("tabpanel");
      await within(panel).findAllByText(/./); // the panel has rendered something
      expect(panel.textContent, `tab "${tab.textContent}"`).not.toMatch(developerText);
    }
    expect(container.textContent).not.toMatch(developerText);
  });

  it("asks only for the monthly fee when adding a subscription plan", async () => {
    mockedFetchAdminVehicles.mockResolvedValue([
      {
        id: 7, brand: 1, brand_name: "Toyota", name: "Alphard", trim: "2.4", body_segment: "mpv", model_year: 2026,
        msrp: "548000.00", min_downpayment: "54800.00", engine_capacity_kw: "201.53", powertrain: "petrol",
        engine_capacity_cc: 2393, spec_complete: true, thumbnail_url: "", is_active: true,
        created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
      },
    ]);
    mockedCreateSubscriptionPlan.mockResolvedValueOnce({
      id: 1, vehicle: 7, vehicle_label: "Toyota Alphard 2.4", fee_monthly: "13700.00", is_active: true,
      created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    });
    const user = userEvent.setup();
    render(<AdminPolicyPage />);
    await screen.findByText("3.50% flat p.a.");

    await user.click(screen.getByRole("tab", { name: "Provider Quote Overrides" }));
    const panel = await screen.findByRole("tabpanel");
    await user.click(await within(panel).findByRole("button", { name: "Add Subscription Plan" }));

    expect(within(panel).getByLabelText("Monthly fee (RM)")).toBeInTheDocument();
    expect(within(panel).queryByLabelText("Insurance (RM/yr)")).not.toBeInTheDocument();
    expect(within(panel).queryByLabelText("Road tax (RM/yr)")).not.toBeInTheDocument();
    expect(within(panel).queryByLabelText("Maintenance (RM/yr)")).not.toBeInTheDocument();

    await user.selectOptions(within(panel).getByLabelText("Vehicle"), "7");
    await user.type(within(panel).getByLabelText("Monthly fee (RM)"), "13700.00");
    await user.click(within(panel).getByRole("button", { name: "Create" }));

    expect(mockedCreateSubscriptionPlan).toHaveBeenCalledWith({ vehicle: 7, fee_monthly: "13700.00" });
  });

  // --- Run 3 fix batch 5 (F-18): words and units, not raw keys ---------------------

  it("shows Residual Override mileage bands in words, not their keys", async () => {
    mockedFetchResidualValueMatrix.mockResolvedValue([
      { id: 1, brand: 1, brand_name: "Toyota", tenure_months: 72, mileage_band: "very_high", residual_value_ratio: "0.3000",
        is_active: true, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" },
      { id: 2, brand: 1, brand_name: "Toyota", tenure_months: 36, mileage_band: "standard", residual_value_ratio: "0.5000",
        is_active: true, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" },
    ]);
    const user = userEvent.setup();
    render(<AdminPolicyPage />);
    await screen.findByText("3.50% flat p.a.");

    await user.click(screen.getByRole("tab", { name: "Residual Overrides" }));
    const panel = await screen.findByRole("tabpanel");

    expect(await within(panel).findByText(bandLabel("very_high"))).toBeInTheDocument();
    expect(within(panel).getByText(bandLabel("standard"))).toBeInTheDocument();
    expect(within(panel).queryByText("very_high")).not.toBeInTheDocument();
  });

  it("shows the interest rate to 2 dp with its unit (the API keeps 4 dp)", async () => {
    render(<AdminPolicyPage />);

    expect(await screen.findByText("3.50% flat p.a.")).toBeInTheDocument();
    expect(screen.queryByText("3.5000")).not.toBeInTheDocument();
  });

  // --- Redesign UI-6a: section navigation, list toolbar, display formatting ------

  it("lists the 8 sections in order as a vertical list, and a Section select switches them too", async () => {
    const user = userEvent.setup();
    render(<AdminPolicyPage />);
    await screen.findByText("3.50% flat p.a.");

    const list = screen.getByRole("tablist", { name: "Policy configuration sections" });
    expect(list).toHaveAttribute("aria-orientation", "vertical");
    expect(within(list).getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Interest Rates", "Residual Overrides", "Residual Estimates", "Default Priority Weights",
      "Operating Costs", "Provider Quote Overrides", "Subscription Estimates", "Contract Penalty Rules",
    ]);
    const select = screen.getByLabelText("Section") as HTMLSelectElement;
    expect(Array.from(select.options).map((option) => option.textContent)).toEqual(
      within(list).getAllByRole("tab").map((tab) => tab.textContent),
    );

    await user.selectOptions(select, "operating-costs");
    expect(screen.getByRole("tab", { name: "Operating Costs" })).toHaveAttribute("aria-selected", "true");
    expect(await within(screen.getByRole("tabpanel")).findByRole("heading", { level: 2, name: "Operating Costs" })).toBeInTheDocument();

    // arrow keys move along the vertical list
    screen.getByRole("tab", { name: "Operating Costs" }).focus();
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("tab", { name: "Provider Quote Overrides" })).toHaveAttribute("aria-selected", "true");
  });

  it("opens each section with a heading, a purpose line and 'How this is used'", async () => {
    render(<AdminPolicyPage />);
    const panel = await screen.findByRole("tabpanel");

    expect(await within(panel).findByRole("heading", { level: 2, name: "Interest Rates" })).toBeInTheDocument();
    expect(within(panel).getByText("Each brand's flat campaign rate, used by Hire Purchase and GFV Leasing.")).toBeInTheDocument();
    expect(within(panel).getByText("How this is used").closest("details")).not.toBeNull();
  });

  it("shows Active rates by default, with counts, and archived ones under Archived / All", async () => {
    mockedFetchInterestRates.mockResolvedValue([
      interestRate,
      { ...interestRate, id: 2, brand_name: "Toyota", rate_percent: "4.0000", is_active: false },
    ]);
    const user = userEvent.setup();
    render(<AdminPolicyPage />);
    await screen.findByText("3.50% flat p.a.");

    expect(screen.queryByText("4.00% flat p.a.")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Active (1)" })).toHaveAttribute("aria-pressed", "true");
    await user.click(screen.getByRole("button", { name: "Archived (1)" }));
    const archivedRow = screen.getByText("4.00% flat p.a.").closest("tr") as HTMLElement;
    expect(within(archivedRow).getByText("Archived")).toBeInTheDocument();
    // an archived rate offers Edit only (as before: no Archive)
    await user.click(within(archivedRow).getByRole("button", { name: "Actions for Toyota interest rate" }));
    expect(screen.getAllByRole("menuitem").map((item) => item.textContent)).toEqual(["Edit"]);
  });

  it("archives a rate from its row menu only after the same confirm dialog", async () => {
    const user = userEvent.setup();
    render(<AdminPolicyPage />);
    await screen.findByText("3.50% flat p.a.");

    await user.click(screen.getByRole("button", { name: "Actions for Toyota interest rate" }));
    await user.click(await screen.findByRole("menuitem", { name: "Archive" }));

    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText("New comparisons for this brand will have no active rate until a replacement is created.")).toBeInTheDocument();
    expect(vi.mocked(archiveInterestRate)).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "Archive" }));
    expect(vi.mocked(archiveInterestRate)).toHaveBeenCalledWith(1);
  });

  it("shows a residual override as a percentage while its edit form keeps the 0-1 ratio", async () => {
    mockedFetchResidualValueMatrix.mockResolvedValue([
      { id: 1, brand: 1, brand_name: "Toyota", tenure_months: 36, mileage_band: "standard", residual_value_ratio: "0.7807",
        is_active: true, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" },
    ]);
    const user = userEvent.setup();
    render(<AdminPolicyPage />);
    await screen.findByText("3.50% flat p.a.");
    await user.click(screen.getByRole("tab", { name: "Residual Overrides" }));
    const panel = await screen.findByRole("tabpanel");

    expect(await within(panel).findByText("78.07%")).toBeInTheDocument();
    expect(within(panel).queryByText("0.7807")).not.toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Actions for Toyota 36 months Standard" }));
    await user.click(await screen.findByRole("menuitem", { name: "Edit" }));
    expect(within(panel).getByLabelText("Residual value ratio (0-1)")).toHaveValue("0.7807");
  });

  it("names the baseline grid's columns from the band API and tints each cell by its share", async () => {
    const user = userEvent.setup();
    render(<AdminPolicyPage />);
    await screen.findByText("3.50% flat p.a.");
    await user.click(screen.getByRole("tab", { name: "Residual Estimates" }));
    const panel = await screen.findByRole("tabpanel");

    const headers = (await within(panel).findAllByRole("columnheader")).map((header) => header.textContent);
    expect(headers.slice(0, 5)).toEqual(["Tenure (mo)", "Low", "Standard", "High", "Very high"]);
    expect(within(panel).getByText("55.00%")).toHaveClass("bg-primary-50");
    expect(within(panel).getByText("42.00%")).toHaveClass("bg-primary-50/60");
  });

  it("keeps a contract rule's full text, one click away", async () => {
    const text = "Normal wear and tear accepted. Excess damage is billed at return.";
    mockedFetchContractPenaltyRules.mockResolvedValue([
      {
        id: 1, brand: 1, brand_name: "Toyota", excess_mileage_charge_per_km: "0.5000", early_termination_months: "3.00",
        wear_tear_tolerance_description: text, source_note: "", is_active: true,
        created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
      },
    ]);
    const user = userEvent.setup();
    render(<AdminPolicyPage />);
    await screen.findByText("3.50% flat p.a.");
    await user.click(screen.getByRole("tab", { name: "Contract Penalty Rules" }));
    const panel = await screen.findByRole("tabpanel");

    const terms = await within(panel).findByText(text);
    expect(terms.closest("details")?.querySelector("summary")).toHaveTextContent("Read the terms");
    expect(within(panel).getByText("0.50")).toBeInTheDocument();
  });

  it("says the reference data could not load and 'Try again' loads it again", async () => {
    mockedFetchAdminBrands.mockReset();
    mockedFetchAdminBrands.mockRejectedValueOnce(new Error("Network Error")).mockResolvedValue([brand]);
    const user = userEvent.setup();
    render(<AdminPolicyPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load brand/vehicle reference data. Please try again.");
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("3.50% flat p.a.")).toBeInTheDocument();
  });
});
