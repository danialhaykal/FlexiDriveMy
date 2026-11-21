import type { PathwayKey } from "./scoring";

export type MileageBand = "low" | "standard" | "high" | "very_high";

// A mileage band as offered to the buyer. THE one list every screen uses (the
// compare screens and the Financial Profile): the API
// (GET /api/comparisons/mileage-bands/, see hooks/useMileageBandOptions)
// supplies each band's label WITH its km range, the range itself, and the km a
// Subscription includes - all from the one backend definition
// (apps/policy/mileage.py, policy data). Run 3 fix batch 6: no km figure is
// written in the frontend; the array below is only what is shown until/unless
// the API answers, so it carries the band names alone.
export interface MileageBandOption {
  value: MileageBand;
  label: string;
  lower_km?: number;
  upper_km?: number;
  included_km_per_year?: number | null;
  representative_km_per_year?: number;
}

export const MILEAGE_BAND_OPTIONS: MileageBandOption[] = [
  { value: "low", label: "Low" },
  { value: "standard", label: "Standard" },
  { value: "high", label: "High" },
  { value: "very_high", label: "Very high" },
];

export interface ComparisonParams {
  vehicle: number;
  tenureMonths: number;
  mileageBand: MileageBand;
  downpayment: string;
}

// All pathway figures below are exactly what apps/comparisons/ returns -
// the frontend only formats them for display, it never recomputes them
// (the project spec: Python is the sole layer that performs financial arithmetic).

export interface HirePurchasePathway {
  monthly_instalment: string;
  upfront_cash: string;
  total_contract_outlay: string;
  // The dealer's FLAT rate (interest on the original balance for the whole
  // term) - what the instalment is built from. Not a reducing-balance rate.
  interest_rate_percent: string;
  // The same instalments as the effective (reducing-balance) rate a bank
  // would disclose, derived server-side. OPTIONAL: a saved scenario's frozen
  // snapshot from before audit batch 3 doesn't have it; null when no
  // positive rate exists.
  effective_rate_percent?: string | null;
}

export interface GfvLeasingPathway {
  monthly_instalment: string;
  upfront_cash: string;
  total_contract_outlay: string;
  balloon_payment: string;
  residual_value_ratio: string;
  // Plain-English origin of that ratio ("Estimate: 42% baseline for 48
  // months / standard mileage, +6 points Toyota, 0 points petrol" or "Admin
  // override for ..."), derived server-side. OPTIONAL: a saved scenario's
  // frozen snapshot from before audit batch 4 doesn't have it.
  residual_basis?: string;
  // Effective (reducing-balance) rate of the lease, balloon included.
  // Optional/nullable for the same reasons as the HP field above.
  effective_rate_percent?: string | null;
  // Run 1 fix batch 4: the end-of-term choice ("At month 36 you choose: pay the
  // balloon of RM ... ") and why the total equals Hire Purchase's - both built
  // by the server. Absent in older snapshots.
  end_of_term_note?: string;
  same_total_note?: string;
  // Run 2 fix batch 2: what the residual is - the lender's conservative
  // guaranteed buy-back value, not a market prediction. Absent in older snapshots.
  // Null (run 2 fix batch 3) when the car's resale curve is not a machine-learning forecast.
  resale_note?: string | null;
}

export interface SubscriptionPathway {
  // QA audit H8: the real, gross fee the subscriber is billed every
  // month (insurance/tax/maintenance are bundled into this one invoice,
  // not charged separately) - never net_cost_after_bundled_benefits
  // below, which is an economic comparison figure only.
  monthly_instalment: string;
  upfront_cash: string;
  total_contract_outlay: string;
  // the project spec's NetCost formula (Fee_monthly minus the annualized
  // insurance/tax/maintenance offset) - informational context only
  // (e.g. "effective cost after bundled extras"), never the headline
  // instalment and never a DSR input.
  // Null when the vehicle can't be costed by the operating-cost engine
  // (incomplete specs / no rate row) - the fee above still shows; the reason
  // is in net_cost_unavailable_reason. Hide the offset when null.
  net_cost_after_bundled_benefits: string | null;
  net_cost_unavailable_reason?: string | null;
  // Audit batch 5 - all derived server-side and OPTIONAL, because a saved
  // scenario's frozen snapshot from before then doesn't carry them.
  // The refundable security deposit: it IS upfront_cash, but it is returned
  // at the end of the term, so it is NOT part of total_contract_outlay.
  refundable_deposit?: string;
  // "quote" = an admin-keyed provider quote; "estimate" = derived from
  // depreciation, funding, running costs and a margin.
  fee_source?: "quote" | "estimate";
  // Plain-English basis of the fee, e.g. "Estimate: depreciation RM ... ".
  fee_basis?: string;
  included_km_per_year?: number;
  // "Includes up to N km a year. Kilometres above that are billed per km (...)."
  mileage_note?: string;
}

export interface ComparisonResult {
  vehicle_id: number;
  tenure_months: number;
  mileage_band: MileageBand;
  downpayment: string;
  // The No-Claim Discount behind the subscription's net-cost offset, from the
  // user's own profile ("0.00" = before NCD). Absent in older snapshots.
  ncd_percent?: string;
  // Null when that pathway's required admin-managed config (interest
  // rate / GFV residual ratio / subscription plan) is missing or
  // inactive - a gap in one pathway's config has nothing to do with
  // whether the other two could be computed, so they're never all
  // wiped out together. See `unavailable` for the specific reason.
  hire_purchase: HirePurchasePathway | null;
  gfv_leasing: GfvLeasingPathway | null;
  subscription: SubscriptionPathway | null;
  // Only lists the pathways that are actually null above, keyed the same
  // way - e.g. {"gfv_leasing": "No active GFV residual ratio configured
  // for brand 'BMW' at 24 months / 'standard' mileage band."}.
  unavailable: Partial<Record<PathwayKey, string>>;
  // FX-3: the most the buyer can put down and still take GFV at this term
  // (the figure the "exceeds the amount financed" reason quotes). Null when
  // GFV has no term to limit; absent in older snapshots.
  gfv_max_downpayment?: string | null;
}
