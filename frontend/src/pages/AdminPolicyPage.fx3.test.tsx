import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AdminPolicyPage } from "./AdminPolicyPage";
import * as policyApi from "../api/policy";
import { fetchAdminBrands, fetchAdminVehicles } from "../api/adminFleet";
import { fetchMileageBands } from "../api/mileageBands";
import { resetMileageBandOptionsCache } from "../hooks/useMileageBandOptions";
import { API_MILEAGE_BANDS } from "../test/mileageBandsFixture";
import type { MCDACriteriaWeight, OperatingCostsResponse } from "../types/policy";
import { formatKwRange, formatWeightPercent, splitSourceNotes } from "../lib/formatPolicy";
import { formatAdminDate, formatAdminDateTime } from "../lib/formatAdminDate";

// FX-3 (X13): Policy Configuration display formatting - weights as percentages (the form still sends the same
// 4-dp values), EV kW groups as readable ranges, a source line once per table, one admin date format.

vi.mock("../api/policy", () => ({
  fetchInterestRates: vi.fn(), createInterestRate: vi.fn(), updateInterestRate: vi.fn(), archiveInterestRate: vi.fn(),
  fetchResidualValueMatrix: vi.fn(), createResidualValueMatrixEntry: vi.fn(), updateResidualValueMatrixEntry: vi.fn(),
  archiveResidualValueMatrixEntry: vi.fn(), fetchMCDAWeights: vi.fn(), updateMCDAWeights: vi.fn(),
  fetchOperatingCosts: vi.fn(), fetchResidualEstimates: vi.fn(), fetchSubscriptionEstimates: vi.fn(),
  fetchSubscriptionPlans: vi.fn(), createSubscriptionPlan: vi.fn(), updateSubscriptionPlan: vi.fn(),
  archiveSubscriptionPlan: vi.fn(), fetchContractPenaltyRules: vi.fn(), createContractPenaltyRule: vi.fn(),
  updateContractPenaltyRule: vi.fn(), archiveContractPenaltyRule: vi.fn(),
}));
vi.mock("../api/mileageBands", () => ({ fetchMileageBands: vi.fn() }));
vi.mock("../api/adminFleet", () => ({ fetchAdminBrands: vi.fn(), fetchAdminVehicles: vi.fn() }));

const WEIGHTS: MCDACriteriaWeight[] = [
  { id: 1, criterion: "upfront_cash_preservation", default_weight: "0.3400", is_active: true, updated_at: "2026-10-30T06:18:00Z" },
  { id: 2, criterion: "maintenance_protection", default_weight: "0.3300", is_active: true, updated_at: "2026-10-30T06:18:00Z" },
  { id: 3, criterion: "ownership_equity", default_weight: "0.3300", is_active: true, updated_at: "2026-10-30T06:18:00Z" },
];

const EV_NOTE = "JPJ kW-based battery-electric road tax, effective 1 Jan 2026.";
const COSTS: OperatingCostsResponse = {
  road_tax_cc_bands: [], archived_diesel_cc_bands: [], cost_rates: [],
  ev_road_tax_groups: [
    { id: 1, label: "A", min_kw: "0.001", max_kw: "100.000", base_amount: "20.00", base_until_kw: "50.00",
      increment_per_10kw: "10.00", source_note: EV_NOTE, effective_from: "2026-01-01" },
    { id: 2, label: "J", min_kw: "910.100", max_kw: "1010.000", base_amount: "8000.00", base_until_kw: "920.00",
      increment_per_10kw: "250.00", source_note: EV_NOTE, effective_from: "2026-01-01" },
    { id: 3, label: "K", min_kw: "1010.100", max_kw: null, base_amount: "20000.00", base_until_kw: null,
      increment_per_10kw: "0.00", source_note: EV_NOTE, effective_from: "2026-01-01" },
  ],
} as unknown as OperatingCostsResponse;

beforeEach(() => {
  vi.resetAllMocks();
  resetMileageBandOptionsCache();
  vi.mocked(fetchMileageBands).mockResolvedValue(API_MILEAGE_BANDS);
  vi.mocked(fetchAdminBrands).mockResolvedValue([]);
  vi.mocked(fetchAdminVehicles).mockResolvedValue([]);
  vi.mocked(policyApi.fetchInterestRates).mockResolvedValue([]);
  vi.mocked(policyApi.fetchResidualValueMatrix).mockResolvedValue([]);
  vi.mocked(policyApi.fetchMCDAWeights).mockResolvedValue(WEIGHTS);
  vi.mocked(policyApi.fetchOperatingCosts).mockResolvedValue(COSTS);
  vi.mocked(policyApi.fetchSubscriptionPlans).mockResolvedValue([]);
  vi.mocked(policyApi.fetchContractPenaltyRules).mockResolvedValue([]);
});

describe("policy display helpers", () => {
  it("reads EV kW groups as ranges", () => {
    expect(formatKwRange("0.001", "100.000")).toBe("Up to 100 kW");
    expect(formatKwRange("910.100", "1010.000")).toBe("Above 910 kW to 1,010 kW");
    expect(formatKwRange("1010.100", null)).toBe("Above 1,010 kW");
    expect(formatKwRange("50", "60")).toBe("From 50 kW to 60 kW");
  });

  it("shows weights as percentages", () => {
    expect(formatWeightPercent("0.3400")).toBe("34%");
    expect(formatWeightPercent("0.3333")).toBe("33.33%");
    expect(formatWeightPercent(0.34 + 0.33 + 0.33)).toBe("100%");
  });

  it("says a shared source once and keeps what each row adds", () => {
    const rows = [
      { source_note: "Planning estimate. Set by the lender." },
      { source_note: "Planning estimate. Set by the lender. Toyota holds its value." },
    ];
    const { common, extra } = splitSourceNotes(rows);
    expect(common).toEqual(["Planning estimate. Set by the lender."]);
    expect(rows.map(extra)).toEqual(["", "Toyota holds its value."]);
    expect(splitSourceNotes([{ source_note: "A one." }, { source_note: "B two." }]).common).toEqual(["A one.", "B two."]);
  });

  it("formats admin dates one way, a date-only value on its own calendar day", () => {
    expect(formatAdminDate("2026-01-01")).toBe("1 Jan 2026");
    expect(formatAdminDate("not a date")).toBe("not a date");
    expect(formatAdminDateTime("2026-10-30T06:18:00Z")).toMatch(/^\d{1,2} Oct 2026, \d{1,2}:18 (am|pm)$/);
  });
});

describe("AdminPolicyPage FX-3", () => {
  it("shows each weight and the running sum as percentages, and still sends the 4-dp values", async () => {
    vi.mocked(policyApi.updateMCDAWeights).mockResolvedValue(WEIGHTS);
    const user = userEvent.setup();
    render(<AdminPolicyPage />);
    await user.click(await screen.findByRole("tab", { name: "Default Priority Weights" }));

    const panel = await screen.findByRole("tabpanel");
    expect(await within(panel).findByText("Running sum: 100%")).toBeInTheDocument();
    expect(within(panel).getByText("34%")).toBeInTheDocument();
    expect(within(panel).getAllByText("33%")).toHaveLength(2);
    expect(within(panel).getByText(/^Last updated: 30 Oct 2026, \d{1,2}:18 (am|pm)$/)).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Save Weights" }));

    expect(policyApi.updateMCDAWeights).toHaveBeenCalledWith([
      { criterion: "upfront_cash_preservation", default_weight: "0.3400" },
      { criterion: "maintenance_protection", default_weight: "0.3300" },
      { criterion: "ownership_equity", default_weight: "0.3300" },
    ]);
  });

  it("reads the EV groups as ranges with whole kW, the source once and the date formatted", async () => {
    const user = userEvent.setup();
    render(<AdminPolicyPage />);
    await user.click(await screen.findByRole("tab", { name: "Operating Costs" }));

    const panel = await screen.findByRole("tabpanel");
    expect(await within(panel).findByText("Up to 100 kW")).toBeInTheDocument();
    expect(within(panel).getByText("Above 910 kW to 1,010 kW")).toBeInTheDocument();
    expect(within(panel).getByText("Above 1,010 kW")).toBeInTheDocument();
    expect(within(panel).getByText("920 kW")).toBeInTheDocument();
    expect(within(panel).queryByText(/910\.100|1010\.000/)).not.toBeInTheDocument();
    expect(within(panel).getAllByText(`Source: ${EV_NOTE}`)).toHaveLength(1);
    expect(within(panel).getAllByText("1 Jan 2026")).toHaveLength(3);
  });
});
