// Display-only formatting for the admin policy tables (redesign UI-6a). The
// API keeps ratios to 4 dp; these only SHOW them in readable units - nothing
// here is ever sent back, and an edit form keeps its own units and value.

// A 0-1 ratio as a percentage to 2 dp: "0.7807" -> "78.07%".
export function formatRatioPercent(value: string | number): string {
  const ratio = Number(value);
  if (Number.isNaN(ratio)) return String(value);
  return `${(ratio * 100).toLocaleString("en-MY", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
}

// A ratio-point adjustment with its sign: "0.0600" -> "+6.00 pts",
// "-0.0800" -> "-8.00 pts", "0.0000" -> "0.00 pts".
export function formatRatioPoints(value: string | number): string {
  const ratio = Number(value);
  if (Number.isNaN(ratio)) return String(value);
  const points = Math.abs(ratio * 100).toLocaleString("en-MY", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (ratio > 0) return `+${points} pts`;
  if (ratio < 0) return `-${points} pts`;
  return `${points} pts`;
}

// A plain amount kept to between 2 and 4 decimals (no trailing zeros past 2):
// "0.5000" -> "0.50", "0.2550" -> "0.255".
export function formatPlainAmount(value: string | number): string {
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  return n.toLocaleString("en-MY", { minimumFractionDigits: 2, maximumFractionDigits: 4 });
}

// FX-3 (X13): a kW figure without trailing zeros: "1010.000" -> "1,010", "50.00" -> "50".
export function formatKw(value: string | number): string {
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  return n.toLocaleString("en-MY", { minimumFractionDigits: 0, maximumFractionDigits: 3 });
}

// FX-3 (X13): an EV road-tax group's motor-power range in words, from the API's
// own bounds. The table stores each lower bound just above the group below it
// ("100.100", or "0.001" for the first), so a fractional lower bound reads as
// "Above 100 kW": "Up to 100 kW", "Above 910 kW to 1,010 kW", "Above 1,010 kW".
export function formatKwRange(minKw: string, maxKw: string | null): string {
  const min = Number(minKw);
  if (Number.isNaN(min)) return maxKw === null ? `${minKw} kW and above` : `${minKw} to ${maxKw} kW`;
  const lower = Number.isInteger(min) ? `From ${formatKw(min)} kW` : `Above ${formatKw(Math.floor(min))} kW`;
  if (maxKw === null) return lower;
  if (min < 1) return `Up to ${formatKw(maxKw)} kW`;
  return `${lower} to ${formatKw(maxKw)} kW`;
}

// FX-3 (X13): a 0-1 weight shown as a percentage, whole where it is whole:
// "0.3400" -> "34%", "0.3333" -> "33.33%", 1 -> "100%". Display only - the
// form still holds and sends the 4-dp value.
export function formatWeightPercent(value: string | number): string {
  const n = Number(value);
  if (Number.isNaN(n)) return String(value);
  const percent = Math.round(n * 1000000) / 10000;
  return `${percent.toLocaleString("en-MY", { minimumFractionDigits: 0, maximumFractionDigits: 2 })}%`;
}

// FX-3 (X13): the source notes of one table, said once. Notes that share the
// same opening sentences give that shared part once ("common") and, per row,
// only what that row adds ("extra", "" when nothing). Identical notes collapse
// to one; notes with nothing in common are each kept whole.
export function splitSourceNotes<T extends { source_note: string }>(
  rows: T[],
): { common: string[]; extra: (row: T) => string } {
  const notes = rows.map((row) => row.source_note.trim()).filter(Boolean);
  if (notes.length === 0) return { common: [], extra: () => "" };
  const sentences = notes.map((note) => note.split(/(?<=\.)\s+/));
  let shared = 0;
  while (sentences.every((s) => s.length > shared && s[shared] === sentences[0][shared])) shared += 1;
  if (shared === 0) return { common: Array.from(new Set(notes)), extra: () => "" };
  const prefix = sentences[0].slice(0, shared).join(" ");
  return {
    common: [prefix],
    extra: (row) => row.source_note.trim().split(/(?<=\.)\s+/).slice(shared).join(" "),
  };
}
