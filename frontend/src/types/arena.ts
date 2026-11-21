import type { ComparisonResult, MileageBand } from "./comparisons";
import type { ForecastSource } from "./depreciation";

export interface ArenaParams {
  vehicles: number[];
  tenureMonths: number;
  mileageBand: MileageBand;
  downpayment: string;
}

// All figures below are exactly what apps/comparisons/ returns - the
// frontend only formats them for display, it never recomputes them
// (the project spec: Python is the sole layer that performs financial
// arithmetic) - same reasoning as comparisons.ts. tco_net stays a
// currency string, never a number, for the same wire-format reason.

export interface ArenaEntry {
  vehicle_id: number;
  ok: boolean;
  // Non-null only when ok is false - a per-vehicle problem (this shared
  // downpayment exceeding this vehicle's own MSRP, or falling below this
  // vehicle's own 10% minimum) severe enough to exclude the vehicle from
  // the arena entirely. This does NOT fail the whole arena request -
  // other vehicles still render.
  error: string | null;
  // Present whenever ok is true, but individual pathways inside it can
  // still be null - see ComparisonResult.unavailable for per-pathway
  // reasons (e.g. GFV unavailable at this tenure/mileage band). Only
  // null when ok is false.
  comparison: ComparisonResult | null;
  // Null when ok is false, OR when ok is true but TCO specifically could
  // not be computed (e.g. no active operating cost band) - the
  // comparison above is still shown in that case. See
  // tco_unavailable_reason for why.
  tco_net: string | null;
  // true when this vehicle's TCO used the straight-line ML fallback
  // (UC006's exception flow) - excluded from the lowest_tco race below.
  model_degraded: boolean | null;
  // Run 2 fix batch 3: why the curve is an estimate - "estimated_curve_unsupported"
  // (the model doesn't cover this car: it sits out of the TCO race by design) or
  // "model_unavailable" (nothing usable is serving). Null on an error entry;
  // absent from older responses, which keep the old "Degraded" wording.
  forecast_source?: ForecastSource | null;
  // Why tco_net is null despite ok being true (e.g. no active operating
  // cost band for this vehicle's engine capacity). Null whenever tco_net
  // is present, and also null (not this) when ok is false - use `error`
  // for that case instead.
  tco_unavailable_reason: string | null;
  // Run 3 fix batch 4 (F-21): the Status row's wording, built by the server
  // ("Available" / "Not available at this downpayment" / "Not available").
  // Null on an error entry; absent from older responses (shown as "Available").
  status_label?: string | null;
}

// QA audit L10: a tie at the winning minimum is reported explicitly, not
// silently resolved to one vehicle - tied_with lists EVERY vehicle_id at
// the minimum (winner_id included), so a component can badge all of them
// by checking membership rather than equality against winner_id alone.
export interface ArenaWinner {
  winner_id: number;
  tied_with: number[];
}

// Each null if fewer than 2 vehicles succeeded, or (lowest_tco only) if
// every "ok" vehicle is model_degraded - a degraded vehicle is still
// shown in `results` with its own model_degraded flag visible, just
// excluded from this specific race rather than picked arbitrarily.
export interface ArenaWinners {
  cheapest_hp: ArenaWinner | null;
  cheapest_gfv: ArenaWinner | null;
  cheapest_subscription: ArenaWinner | null;
  lowest_tco: ArenaWinner | null;
}

export interface ArenaResult {
  results: ArenaEntry[];
  winners: ArenaWinners;
}
