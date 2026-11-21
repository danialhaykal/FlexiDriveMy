import type { MileageBand } from "./comparisons";
import type { PaginatedResponse } from "./catalog";

// Batch 6A - mirrors apps/policy/serializers.py exactly. Every admin
// CRUD page only displays/edits these fields and shows the server's own
// validation messages verbatim (the project spec: Python is the sole layer that
// performs financial arithmetic/validation; the frontend never
// re-derives a boundary rule itself).

export interface InterestRate {
  id: number;
  brand: number;
  brand_name: string;
  rate_percent: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ResidualValueMatrixEntry {
  id: number;
  brand: number;
  brand_name: string;
  tenure_months: number;
  mileage_band: MileageBand;
  residual_value_ratio: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface SubscriptionPlan {
  id: number;
  vehicle: number;
  vehicle_label: string;
  fee_monthly: string;
  // The API still returns the three deprecated annual cost columns, but nothing
  // reads them: road tax, insurance and maintenance are derived per vehicle by
  // apps.policy.operating_costs (see OperatingCostsResponse below).
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

// GET /policy/operating-costs/ - the three admin-managed rate tables the
// operating-cost engine reads (read-only here; edited in Django admin).
export interface RoadTaxCcBandRow {
  id: number;
  // The JPJ registration class whose table this band is in (petrol and
  // diesel alike read it).
  vehicle_class: "saloon" | "non_saloon";
  vehicle_class_label: string;
  // No longer read; only labels the archived diesel rows.
  fuel_schedule: "petrol" | "diesel";
  min_cc: number;
  max_cc: number;
  base_amount: string;
  threshold_cc: number;
  per_cc_rate: string;
  source_note: string;
  effective_from: string;
  is_active: boolean;
}

export interface EvRoadTaxGroupRow {
  id: number;
  label: string;
  min_kw: string;
  max_kw: string | null;
  base_amount: string;
  base_until_kw: string | null;
  increment_per_10kw: string;
  source_note: string;
  effective_from: string;
}

export interface OperatingCostRateRow {
  id: number;
  powertrain: string;
  powertrain_label: string;
  insurance_rate_percent: string;
  maintenance_rate_percent: string;
  maintenance_floor_annual: string;
  // Planning-assumption ceiling; null = no cap.
  maintenance_cap_annual: string | null;
  source_note: string;
  effective_from: string;
}

export interface OperatingCostsResponse {
  // Active bands only, saloon and non-saloon.
  road_tax_cc_bands: RoadTaxCcBandRow[];
  // The old diesel schedule: archived, kept for the record, never used.
  archived_diesel_cc_bands: RoadTaxCcBandRow[];
  ev_road_tax_groups: EvRoadTaxGroupRow[];
  cost_rates: OperatingCostRateRow[];
}
// GET /policy/residual-estimates/ - what the GFV residual estimator reads
// (read-only here; edited in Django admin). Every row is a planning
// assumption and carries a source_note saying so.
export interface ResidualBaselineRow {
  id: number;
  tenure_months: number;
  mileage_band: MileageBand;
  ratio: string;
  source_note: string;
  effective_from: string;
}

export interface ResidualAdjustmentRow {
  id: number;
  // Exactly one of brand / powertrain is set.
  brand: number | null;
  brand_name: string | null;
  powertrain: string;
  powertrain_label: string;
  delta_points: string;
  source_note: string;
  effective_from: string;
}

export interface ResidualEstimatesResponse {
  baselines: ResidualBaselineRow[];
  adjustments: ResidualAdjustmentRow[];
}

// GET /policy/subscription-estimates/ - the planning assumptions every
// Subscription fee is estimated from (read-only here; edited in Django admin).
export interface SubscriptionPolicyRow {
  id: number;
  min_tenure_months: number;
  max_tenure_months: number;
  funding_rate_percent: string;
  margin_percent: string;
  deposit_months: string;
  // Run 3 fix batch 6: each mileage band's limit / included km a year (policy data).
  low_km_cap?: number;
  standard_km_cap?: number;
  high_km_cap?: number;
  very_high_km_cap: number;
  source_note: string;
  effective_from: string;
}

export interface SubscriptionEstimatesResponse {
  policies: SubscriptionPolicyRow[];
}

export interface ContractPenaltyRule {
  id: number;
  // null brand = the single DEFAULT rule every brand without its own row uses.
  brand: number | null;
  brand_name: string | null;
  excess_mileage_charge_per_km: string;
  // Months of the instalment owed on early termination; empty on a brand rule
  // means "use the default rule's".
  early_termination_months: string | null;
  wear_tear_tolerance_description: string;
  source_note: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export type MCDACriterion = "upfront_cash_preservation" | "maintenance_protection" | "ownership_equity";

export const MCDA_CRITERION_LABELS: Record<MCDACriterion, string> = {
  upfront_cash_preservation: "Upfront Cash Preservation",
  maintenance_protection: "Maintenance Protection",
  ownership_equity: "Ownership Equity",
};

export interface MCDACriteriaWeight {
  id: number;
  criterion: MCDACriterion;
  default_weight: string;
  is_active: boolean;
  updated_at: string;
}

export type InterestRateListResponse = PaginatedResponse<InterestRate>;
export type ResidualValueMatrixListResponse = PaginatedResponse<ResidualValueMatrixEntry>;
export type SubscriptionPlanListResponse = PaginatedResponse<SubscriptionPlan>;
export type ContractPenaltyRuleListResponse = PaginatedResponse<ContractPenaltyRule>;
