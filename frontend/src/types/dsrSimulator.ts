import type { MileageBand } from "./comparisons";
import type { PathwayKey } from "./scoring";

// All figures below are exactly what apps/scoring/'s DSR Simulator
// endpoint returns - the frontend only formats and displays them (same
// "never recompute a financial figure" rule as every other types file
// here). is_ccris_reportable is a plain structural label, not derived
// from anything computed - HP/GFV Leasing are credit agreements reported
// to CCRIS, Subscription is a service contract with no credit facility
// behind it.

export interface DsrSimulatorParams {
  vehicle: number;
  tenureMonths: number;
  mileageBand: MileageBand;
  downpayment: string;
  monthlyIncome: string;
  maxDsrPercent: string;
  existingMonthlyCommitments: string;
}

export interface DsrSimulatorPathway {
  monthly_instalment: string;
  existing_monthly_commitments: string;
  dsr_percent: string;
  exceeds_dsr: boolean;
  // Run 3 fix batch 5 (F-23): see PathwayScore.dsr_note.
  dsr_note?: string | null;
  is_ccris_reportable: boolean;
}

// Only the pathways that could actually be simulated - a pathway missing
// its own F010/F011 config is absent here and listed in `unavailable`
// with its reason instead.
export type DsrSimulatorPathways = Partial<Record<PathwayKey, DsrSimulatorPathway>>;

export interface DsrSimulatorResult {
  vehicle_id: number;
  monthly_income: string;
  max_dsr_percent: string;
  pathways: DsrSimulatorPathways;
  unavailable: Partial<Record<PathwayKey, string>>;
}
