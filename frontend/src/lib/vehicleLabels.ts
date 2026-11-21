import { BODY_SEGMENT_OPTIONS, POWERTRAIN_OPTIONS } from "../types/catalog";
import type { Vehicle } from "../types/catalog";

// Display labels for a car's specs, shared by the catalog card and the vehicle
// page. Labels and units only - never a financial figure.

// QA audit Cosmetic: CSS `capitalize` on the raw "suv"/"mpv" value produced
// "Suv"/"Mpv"; the BODY_SEGMENT_OPTIONS labels have the right "SUV"/"MPV".
export function bodySegmentLabel(value: Vehicle["body_segment"] | "" | null | undefined): string {
  if (!value) return "";
  return BODY_SEGMENT_OPTIONS.find((option) => option.value === value)?.label ?? value;
}

export function powertrainLabel(value: Vehicle["powertrain"]): string {
  return POWERTRAIN_OPTIONS.find((option) => option.value === value)?.label ?? value;
}

// "150 kW" from the API's power figure ("150.00"; the trailing ".00" is only
// display); "" when there is no usable figure - never "null" or a guess.
export function formatPowerKw(kw: string | null | undefined): string {
  if (!kw) return "";
  const value = Number(kw);
  // FX-2 (item 7): whole kW for display (201.53 -> 202 kW); the API value is unchanged.
  return Number.isFinite(value) && value > 0 ? `${Math.round(value)} kW` : "";
}
