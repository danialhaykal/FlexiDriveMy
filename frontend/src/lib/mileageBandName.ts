import type { MileageBandOption } from "../types/comparisons";

// The NAME of a mileage band ("Standard"), never its km range. A saved
// comparison shows only the name: one saved before the 22 Oct 2026 band change
// was priced on different km limits, so today's range would misdescribe it.
// The name comes from the band API's own label (the text before the dash) -
// no band text is written here.

// "Standard — <its km range>" -> "Standard"; a label with no dash
// (the built-in list shown until the API answers) is already the name.
export function bandNameFromLabel(label: string): string {
  return label.split(/\s+[—–-]\s+/)[0].trim();
}

// The band's name from the API's list; a key the list doesn't have is shown
// title-cased ("very_high" -> "Very High"); no key -> "".
export function mileageBandName(key: string | null | undefined, bands: MileageBandOption[]): string {
  if (!key) return "";
  const band = bands.find((option) => option.value === key);
  if (band) return bandNameFromLabel(band.label);
  return key
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}
