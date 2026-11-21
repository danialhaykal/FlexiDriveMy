import type { MileageBandOption } from "../types/comparisons";

// Run 3 fix batch 6: THE one copy, for frontend tests, of what
// GET /api/comparisons/mileage-bands/ serves - mirroring the backend's one band
// definition (apps/policy/mileage.py, from the subscription policy's seeded
// limits). The app itself never writes a band km figure; tests import their band
// data from here, and noHardCodedBandText.test.ts allows band km text only in
// this file.
export const API_MILEAGE_BANDS: MileageBandOption[] = [
  { value: "low", label: "Low — up to 10,000 km/year", lower_km: 0, upper_km: 10000, included_km_per_year: 10000, representative_km_per_year: 8000 },
  { value: "standard", label: "Standard — 10,001 to 15,000 km/year", lower_km: 10000, upper_km: 15000, included_km_per_year: 15000, representative_km_per_year: 12500 },
  { value: "high", label: "High — 15,001 to 25,000 km/year", lower_km: 15000, upper_km: 25000, included_km_per_year: 25000, representative_km_per_year: 20000 },
  { value: "very_high", label: "Very high — above 25,000 km/year", lower_km: 25000, upper_km: 35000, included_km_per_year: 35000, representative_km_per_year: 30000 },
];

// A Subscription mileage note as a snapshot saved BEFORE Run 3 fix batch 6 stored it
// (standard then ran up to 20,000 km a year): an old snapshot shows it as saved.
export const PRE_BATCH6_STANDARD_MILEAGE_NOTE =
  "Includes up to 20,000 km a year. Kilometres above that are billed per km (RM 0.50/km under the default contract rule).";
export const PRE_BATCH6_STANDARD_INCLUDED_KM = 20000;

export function bandLabel(value: string): string {
  return API_MILEAGE_BANDS.find((band) => band.value === value)?.label ?? value;
}

// The Subscription's included-mileage note as the server builds it, for a band.
export function includedMileageNote(value: string): string {
  const km = API_MILEAGE_BANDS.find((band) => band.value === value)?.included_km_per_year ?? 0;
  return `Includes up to ${km.toLocaleString("en-MY")} km a year.`;
}
