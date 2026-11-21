import type { MileageBand } from "./comparisons";
import type { PathwayKey } from "./scoring";

export interface TcoParams {
  vehicle: number;
  tenureMonths: number;
  mileageBand: MileageBand;
  downpayment: string;
}

// All figures below are exactly what apps/depreciation/ returns - the
// frontend only formats and charts them, it never recomputes them
// (the project spec: Python is the sole layer that performs financial/ML-derived
// arithmetic).

export interface MonthlyForecastPoint {
  month: number;
  predicted_resale_value: string;
  hp_outstanding_balance: string;
}

// F012 explainability add-on: real SHAP per-factor contributions for
// the predicted resale value at the user's selected tenure. base_value
// + sum(contributions values) == predicted_value (verified server-side -
// see apps/depreciation/tests/test_explanation.py). ML batch 1: base_value
// is the car's new price; each factor's share of the change was worked out
// on the model's log scale and shared in proportion, server-side.
// Run 3 fix batch 5 (F-03): 2-dp currency strings like every other money field;
// a comparison saved before that holds plain numbers, so both are accepted and
// shown the same way (ExplanationAmount).
export type ExplanationAmount = string | number;

export interface ResaleValueExplanation {
  base_value: ExplanationAmount;
  contributions: {
    vehicle_age: ExplanationAmount;
    mileage: ExplanationAmount;
    brand_code: ExplanationAmount;
    engine_litres: ExplanationAmount;
    body_type: ExplanationAmount;
    recond: ExplanationAmount;
  };
  predicted_value: ExplanationAmount;
}

// Batch 6C / UC006 steps 6-9 additions below.

// The same three UNWEIGHTED per-pathway scores UC007's suitability
// scoring computes (apps.scoring.formulas) - see
// apps.depreciation.services._build_risk_radar. Decimal strings, same
// reasoning as every other currency/ratio field here.
export interface RiskRadarPathwayScores {
  upfront_cash_preservation: string;
  maintenance_protection: string;
  ownership_equity: string;
}

export interface CumulativeCashFlowPoint {
  month: number;
  cumulative_cash_outflow: string;
}

// Settling a Hire Purchase loan early (run 1): the reducing-balance amount to
// settle, no penalty - computed server-side by settlement_balance.
export interface EarlySettlement {
  method: "reducing_balance";
  // null when the loan is 12 months or shorter.
  after_12_months: string | null;
  at_half_term: string;
  half_term_month: number;
  penalty: "none";
}

export interface ContractChecklist {
  excess_mileage_charge_per_km: string;
  // Run 1 - all OPTIONAL: a saved snapshot from before then has none of them
  // (and has early_termination_amount instead), and must render as saved.
  early_settlement?: EarlySettlement;
  // Months of the SUBSCRIPTION fee for returning a subscription car early, and
  // that many months of this request's Subscription fee (null when
  // Subscription isn't available for this tenure).
  subscription_early_return_months?: string | null;
  subscription_early_return_fee?: string | null;
  // Still sent (same months as subscription_early_return_months). In a
  // snapshot saved between audit batch 4 and run 1 it meant months of the HP
  // instalment, with early_termination_amount (no longer sent) beside it.
  early_termination_months?: string | null;
  early_termination_amount?: string | null;
  // "brand" | "default": which ContractPenaltyRule applied; and where the
  // months came from (a brand rule may leave them empty to inherit the default's).
  rule_source?: "brand" | "default";
  early_termination_months_source?: "brand" | "default" | null;
  // Legacy snapshots only - no longer sent.
  early_termination_fee?: string;
  wear_tear_tolerance_description: string;
}

export type RiskAlertSeverity = "warning" | "info";

export interface RiskAlert {
  code: string;
  severity: RiskAlertSeverity;
  message: string;
}

// One pathway's total cost of ownership (apps.depreciation.services.
// build_pathway_tco). Every money field is a 2 dp string, or null when the
// pathway isn't available for this request (unavailable_reason says why).
export interface PathwayTcoEntry {
  available: boolean;
  unavailable_reason: string | null;
  horizon_months: number;
  upfront_cash: string | null;
  payments_total: string | null;
  balloon_paid: string | null;
  running_costs_total: string | null;
  resale_credit: string | null;
  settlement_debit: string | null;
  deposit_refund: string | null;
  gross: string | null; // "What you pay"
  amount_back: string | null; // "What you get back" (gross - net)
  net: string | null;
  net_per_month: string | null; // "Net cost per month of use"
  // GFV entries only: what the buy-back guarantee is worth on this forecast.
  gfv_guarantee_value?: string | null;
}

export type PathwayTcoKey = "hire_purchase" | "gfv_retain" | "gfv_return" | "subscription";
export type PathwayTco = Record<PathwayTcoKey, PathwayTcoEntry>;

export type ForecastSource = "ml_model" | "estimated_curve_unsupported" | "model_unavailable";

export interface TcoReport {
  vehicle_id: number;
  tenure_months: number;
  mileage_band: MileageBand;
  downpayment: string;
  hp_monthly: string;
  // true when the ML service failed/timed out and monthly_forecast is the
  // straight-line depreciation fallback (UC006's exception flow).
  model_degraded: boolean;
  degraded_reason: string | null;
  // Run 2 fix batch 3: where the curve comes from, as the server decided it.
  // "estimated_curve_unsupported" = a car the model doesn't cover (electric, no
  // engine size, body type not mapped): shown as a neutral "Estimated curve".
  // "model_unavailable" = nothing usable is serving: the amber "Degraded".
  // Absent from a snapshot saved before it existed - that keeps the old
  // behaviour (model_degraded alone decides).
  forecast_source?: ForecastSource;
  // Always 61 entries, months 0-60 inclusive.
  monthly_forecast: MonthlyForecastPoint[];
  tco_gross: string;
  tco_net: string;
  road_tax_annual: string;
  insurance_annual: string;
  maintenance_annual: string;
  // Run 1 fix batch 4: TCO for every pathway (tco_gross/tco_net above stay
  // the Hire Purchase figures). Absent in snapshots saved before it existed.
  pathway_tco?: PathwayTco;
  // The No-Claim Discount the server applied to insurance_annual, from the
  // user's own profile ("0.00" = before NCD). Absent in older snapshots.
  ncd_percent?: string;
  // Plain-English basis for each of the three figures above, e.g.
  // "1,998 cc petrol, saloon - JPJ cc schedule" (apps.policy.operating_costs).
  // OPTIONAL: a saved scenario's frozen payload from before audit batch 2
  // doesn't have it.
  operating_cost_basis?: {
    road_tax: string;
    insurance: string;
    maintenance: string;
  };
  // FX-3: the yearly maintenance cap the engine applied (null = no cap).
  // Absent in older snapshots.
  operating_cost_policy?: {
    maintenance_cap_annual: string | null;
  };
  // Both null unless predicted resale value falls below the outstanding
  // loan balance at some point (UC006 9.4-9.5).
  negative_equity_crossover_month: number | null;
  negative_equity_shortfall_amount: string | null;
  // Null whenever model_degraded is true or the explanation itself
  // failed server-side - never a separate error state.
  resale_value_explanation: ResaleValueExplanation | null;
  // Keyed by whichever pathways build_comparison() actually returned for
  // this vehicle/tenure/mileage/downpayment combination - a pathway
  // missing its own F010/F011 config is absent here, named instead in
  // radar_unavailable (same shape as ComparisonResult.unavailable).
  //
  // `| undefined` on this and every other Batch 6C field below is real,
  // not defensive typing: a scenario saved via UC009 BEFORE Batch 6C
  // added these fields has none of these keys at all in its stored
  // `scenarios` row - SavedScenarioPage.tsx renders that old payload
  // completely unchanged (by design - see its own top-of-file comment),
  // so a TcoReport reconstructed from an old snapshot genuinely lacks
  // them. The LIVE /api/depreciation/tco/ endpoint always includes every
  // one of these fields (see apps.depreciation.serializers.
  // TCOResultSerializer) - this looseness exists only to describe what a
  // pre-6C saved snapshot can actually contain, not a live-path
  // possibility.
  risk_radar: Partial<Record<PathwayKey, RiskRadarPathwayScores>> | undefined;
  radar_unavailable: Partial<Record<PathwayKey, string>> | undefined;
  // Always 61 entries, months 0-60 inclusive - the HP pathway's running
  // cash outlay. By construction, the last entry's cumulative_cash_outflow
  // equals tco_gross (verified server-side).
  cumulative_cash_flow: CumulativeCashFlowPoint[] | undefined;
  // Null when this vehicle's brand has no active ContractPenaltyRule
  // configured (Batch 6A) - genuinely optional, unlike every other field
  // on this report. Undefined (distinct from that explicit null) only on
  // a pre-6C saved snapshot - see this interface's own top note.
  contract_checklist: ContractChecklist | null | undefined;
  // Never null on the live path - an empty array when neither alert
  // condition fires. Undefined only on a pre-6C saved snapshot - see
  // this interface's own top note.
  risk_alerts: RiskAlert[] | undefined;
  // Run 2 fix batch 2 (E3, C6, E5): sentences built by the server, shown as-is.
  // resale_views_note: why the lender's GFV residual and the predicted market
  // value differ (null when there is no GFV for this tenure, or the curve is the
  // estimated fallback). resale_forecast_note: what the predicted curve is and
  // its typical error (null on the fallback curve). Both are absent from a
  // snapshot saved before they existed.
  resale_views_note?: string | null;
  resale_forecast_note?: string | null;
  // Run 3 fix batch 6: "The forecast is capped at the mileage the model has seen." when
  // the cap changed the machine-learning curve; null otherwise, absent from older snapshots.
  forecast_cap_note?: string | null;
}
