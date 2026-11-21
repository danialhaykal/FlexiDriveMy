import type { MileageBand } from "./comparisons";

export type PathwayKey = "hire_purchase" | "gfv_leasing" | "subscription";

export const PATHWAY_LABELS: Record<PathwayKey, string> = {
  hire_purchase: "Hire Purchase",
  gfv_leasing: "GFV Leasing",
  subscription: "Subscription",
};

export interface ScoringParams {
  vehicle: number;
  tenureMonths: number;
  mileageBand: MileageBand;
  downpayment: string;
  upfrontCashPreservation: number;
  maintenanceProtection: number;
  ownershipEquity: number;
  monthlyIncome: string;
  maxDsrPercent: string;
}

// All figures below are exactly what apps/scoring/ returns - the
// frontend only formats and displays them, it never recomputes the MCDA
// weights, suitability scores, DSR percentages, or ranking (the project spec:
// Python is the sole layer that performs this arithmetic).

export interface ScoringWeights {
  upfront_cash_preservation: string;
  maintenance_protection: string;
  ownership_equity: string;
}

export interface PathwayScore {
  monthly_instalment: string;
  upfront_cash: string;
  dsr_percent: string;
  exceeds_dsr: boolean;
  // Run 3 fix batch 5 (F-23): server-built words when the 2-dp DSR reads as the limit but is over it;
  // null otherwise, absent from older snapshots.
  dsr_note?: string | null;
  suitability_score: string;
}

// Only the pathways that could actually be scored (UC007 step 3: "scores
// each available pathway") - a pathway missing its own F010/F011 config
// is absent here and listed in `unavailable` with its reason instead.
export type ScoringPathways = Partial<Record<PathwayKey, PathwayScore>>;

export interface ScoringResult {
  vehicle_id: number;
  weights: ScoringWeights;
  monthly_income: string;
  max_dsr_percent: string;
  pathways: ScoringPathways;
  ranking: PathwayKey[];
  // null when every pathway exceeds the DSR limit, or when none were
  // available to begin with - `rationale` explains which, verbatim from
  // the API either way.
  recommended_pathway: PathwayKey | null;
  rationale: string;
  unavailable: Partial<Record<PathwayKey, string>>;
}
