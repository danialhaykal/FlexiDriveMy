import type { MileageBand } from "../types/comparisons";

// Run 1 fix batch 5 (M4): the compare page's inputs live in its query string
// (?tenure=60&mileage=standard&downpayment=26580.00) so a refresh or a copied
// link keeps them. Anything invalid is simply ignored (null) and the page
// falls back to the profile / defaults - never an error page. The server
// still validates every request; this only decides what to pre-fill.

const MIN_TENURE = 12;
const MAX_TENURE = 108;
const BANDS: readonly string[] = ["low", "standard", "high", "very_high"];

// Run 3 fix batch 5 (F-30c): the client's check says exactly what the API says
// (backend comparisons/scoring/depreciation serializers and the Arena).
export const DOWNPAYMENT_NOT_BELOW_PRICE_MESSAGE = "Downpayment must be less than the vehicle's price.";
// FX-2 (item 5): a downpayment of exactly the price is a cash purchase - nothing to finance. The validation is unchanged
// (no request is sent); this is the sentence the buyer reads for that one case.
export const DOWNPAYMENT_OUTRIGHT_MESSAGE =
  "Buying outright? With a 100% downpayment there is nothing to finance, so these options don't apply.";

export interface CompareParams {
  tenureMonths: number | null;
  mileageBand: MileageBand | null;
  downpayment: string | null;
}

export function readCompareParams(params: URLSearchParams): CompareParams {
  const tenureRaw = params.get("tenure");
  const tenure = tenureRaw !== null && /^\d+$/.test(tenureRaw) ? Number(tenureRaw) : NaN;
  const band = params.get("mileage");
  const downpaymentRaw = params.get("downpayment");
  return {
    tenureMonths: Number.isInteger(tenure) && tenure >= MIN_TENURE && tenure <= MAX_TENURE ? tenure : null,
    mileageBand: band !== null && BANDS.includes(band) ? (band as MileageBand) : null,
    downpayment: downpaymentRaw !== null && /^\d+(\.\d{1,2})?$/.test(downpaymentRaw) ? downpaymentRaw : null,
  };
}

// A link's downpayment is only kept if it is a usable one for THIS car (at
// least the 10% minimum, below the price); otherwise the minimum is used.
// A comparison of two API strings as numbers - no figure is derived.
export function downpaymentForVehicle(fromUrl: string | null, minDownpayment: string, msrp: string): string {
  if (fromUrl === null) return minDownpayment;
  const value = Number(fromUrl);
  return value >= Number(minDownpayment) && value < Number(msrp) ? fromUrl : minDownpayment;
}

export function writeCompareParams(
  params: URLSearchParams,
  values: { tenureMonths: number; mileageBand: MileageBand; downpayment: string },
): URLSearchParams {
  const next = new URLSearchParams(params);
  next.set("tenure", String(values.tenureMonths));
  next.set("mileage", values.mileageBand);
  if (values.downpayment.trim() === "") next.delete("downpayment");
  else next.set("downpayment", values.downpayment);
  return next;
}
