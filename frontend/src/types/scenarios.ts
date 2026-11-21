import type { ComparisonResult, MileageBand } from "./comparisons";
import type { TcoReport } from "./depreciation";
import type { ScoringResult } from "./scoring";

// The AI Recommendation request the buyer actually sent (snake_case, as
// the API takes it). Ratings are 1-5; income and DSR limit are the strings
// typed into those fields.
export interface ScoringRequestInputs {
  upfront_cash_preservation: number;
  maintenance_protection: number;
  ownership_equity: number;
  monthly_income: string;
  max_dsr_percent: string;
}

// What "Save this Comparison" sends: the inputs only. The server
// calculates every figure from these with the same services as the live
// screens (run 1 fix batch 2) - this app never sends a figure to be saved.
export interface ScenarioInputs {
  tenure_months: number;
  mileage_band: MileageBand;
  downpayment: string;
  include_tco: boolean;
  scoring: ScoringRequestInputs | null;
}

// UC009: a snapshot of the figures at save time, stored server-side and
// rendered as-is on reload - never by re-calling F005/F006/F007 - so it
// stays as it was even if pricing config (rates, residual ratios, operating
// costs) changes later.
export interface ScenarioPayload {
  tenureMonths: number;
  mileageBand: MileageBand;
  downpayment: string;
  comparison: ComparisonResult;
  tco: TcoReport | null; // null if the user never opened that tab, or it couldn't be calculated
  scoring: ScoringResult | null; // null if the user never opened that tab
  // True only if the user had "I prefer Islamic financing" ticked when they
  // saved - the snapshot then says "profit rate" (wording only). Absent in
  // older snapshots and whenever it was off.
  prefersIslamicFinancing?: boolean;
  // All absent on rows saved before the server built snapshots.
  snapshotVersion?: number; // 2 = calculated by the server from `inputs`
  builtBy?: "server";
  tcoUnavailableReason?: string; // why `tco` is null although the TCO tab was open
  // The inputs as the server recorded them, plus the No-Claim Discount it
  // read from the profile at save time (never sent by this app).
  inputs?: ScenarioInputs & { ncd_percent?: string };
}

export interface Scenario {
  id: number;
  title: string;
  vehicle: number;
  vehicle_label: string;
  payload: ScenarioPayload;
  created_at: string;
  updated_at: string;
}
