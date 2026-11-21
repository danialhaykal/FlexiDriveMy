import type { MileageBand } from "./comparisons";
import type { PathwayKey } from "./scoring";

// All figures below are exactly what apps/depreciation/'s Total-Loss
// Sandbox endpoint returns - the frontend only formats and displays them
// (same "never recompute a financial figure" rule as every other types
// file here). has_ownership_exposure is a plain structural label, not
// derived from anything computed - Subscription has no ownership stake,
// so its outstanding_balance/net_position are genuinely not applicable
// (null), not zero.

export interface TotalLossSandboxParams {
  vehicle: number;
  tenureMonths: number;
  mileageBand: MileageBand;
  downpayment: string;
  lossMonth: number;
  excessAmount: string;
}

export interface TotalLossSandboxPathway {
  // QA audit L8: null for Subscription - no ownership stake means no
  // insurance claim on the vehicle that's theirs to receive (same
  // "genuinely not applicable" reasoning as outstanding_balance/
  // net_position below, not a computed zero).
  insurance_payout: string | null;
  outstanding_balance: string | null;
  net_position: string | null;
  has_ownership_exposure: boolean;
}

export interface TotalLossSandboxResult {
  vehicle_id: number;
  tenure_months: number;
  mileage_band: MileageBand;
  downpayment: string;
  loss_month: number;
  excess_amount: string;
  // true when the ML service failed/timed out and the resale valuation
  // used is the straight-line depreciation fallback (same meaning as
  // TcoReport's own model_degraded).
  model_degraded: boolean;
  degraded_reason: string | null;
  // QA audit L8: true when loss_month > 60 - the resale value used is
  // reused from month 60 (the model's own prediction horizon), not a
  // genuine prediction for the actual loss month chosen.
  resale_value_is_plateaued: boolean;
  // Each null when that pathway's required admin-managed config (interest
  // rate / GFV residual ratio) is missing or inactive - see `unavailable`
  // for the specific reason. Subscription is wholly independent so it's
  // only null if no SubscriptionPlan exists for this vehicle at all.
  hire_purchase: TotalLossSandboxPathway | null;
  gfv_leasing: TotalLossSandboxPathway | null;
  subscription: TotalLossSandboxPathway | null;
  unavailable: Partial<Record<PathwayKey, string>>;
}
