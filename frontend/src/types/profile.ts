import type { MileageBand } from "./comparisons";

// Mirrors apps/profiles/models.py / serializers.py exactly (UC003).

export type OwnershipPreference = "retain" | "upgrade";

export const OWNERSHIP_PREFERENCE_OPTIONS: { value: OwnershipPreference; label: string }[] = [
  { value: "retain", label: "Retain the vehicle" },
  { value: "upgrade", label: "Upgrade at contract end" },
];

// The standard Malaysian No-Claim Discount steps, exactly as the API stores
// them (apps/profiles/models.py NCD_STEPS). The value is only displayed and
// sent back - the server applies it to insurance.
export const NCD_OPTIONS: { value: string; label: string }[] = [
  { value: "0.00", label: "0%" },
  { value: "25.00", label: "25%" },
  { value: "30.00", label: "30%" },
  { value: "38.33", label: "38.33%" },
  { value: "45.00", label: "45%" },
  { value: "55.00", label: "55%" },
];
export const NCD_LABEL = "No-Claim Discount (NCD) on your current car insurance";
export const NCD_HELP_TEXT = "Check your last insurance renewal notice. New drivers start at 0%.";

export interface FinancialProfile {
  id: number;
  monthly_budget: string;
  preferred_tenure_months: number;
  // The same four bands as the compare screens (one shared list - see
  // hooks/useMileageBandOptions). A profile saved before that may hold an old
  // literal-km value; the API maps it on read, and mapAnnualMileageBandToMileageBand
  // below still copes if one ever reaches the page.
  annual_mileage_band: MileageBand;
  ownership_preference: OwnershipPreference;
  shariah_compliant_required: boolean;
  // One of NCD_OPTIONS' values; "0.00" for a profile saved before NCD existed.
  ncd_percent: string;
  // Run 1 fix batch 5: prefills for the AI Recommendation and Affordability
  // tabs (still editable per comparison). Income is optional (null).
  monthly_income?: string | null;
  max_dsr_percent?: string;
  created_at: string;
  updated_at: string;
}

export interface FinancialProfilePayload {
  monthly_budget: string;
  preferred_tenure_months: number;
  // The same four bands as the compare screens (one shared list - see
  // hooks/useMileageBandOptions). A profile saved before that may hold an old
  // literal-km value; the API maps it on read, and mapAnnualMileageBandToMileageBand
  // below still copes if one ever reaches the page.
  annual_mileage_band: MileageBand;
  ownership_preference: OwnershipPreference;
  shariah_compliant_required: boolean;
  ncd_percent: string;
  // "" = not given (sent as null).
  monthly_income: string;
  max_dsr_percent: string;
}

// The profile's default DSR limit (apps/profiles/models.py).
export const DEFAULT_MAX_DSR_PERCENT = "60.00";

const LEGACY_MILEAGE_VALUES: Record<string, MileageBand> = {
  // An OLD stored value maps to the band the user effectively chose when it was
  // saved - a frozen mapping, the same one the backend uses
  // (apps/profiles/models.py), kept when the band ranges were recalibrated
  // (Run 3 fix batch 6). None maps to "low".
  "10000": "standard",
  "20000": "high",
  "30000": "very_high",
};

const CURRENT_BANDS: readonly string[] = ["low", "standard", "high", "very_high"];

// Any stored profile mileage value -> a current band, never throwing: a current
// band is returned as is, an old km value is mapped, anything unrecognised
// falls back to "standard" (the default band) rather than breaking the page.
export function mapAnnualMileageBandToMileageBand(band: string): MileageBand {
  if (CURRENT_BANDS.includes(band)) return band as MileageBand;
  return LEGACY_MILEAGE_VALUES[band] ?? "standard";
}