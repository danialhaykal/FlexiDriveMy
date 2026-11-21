// Presentational number formatting only - these never derive a new
// financial figure, only reformat one the API already returned
// (the project spec: Python is the sole layer that performs financial
// arithmetic; the on-screen, saved, and PDF-exported values must always
// be identical to what the API sent).

// "5344.44" -> "RM 5,344.44"
export function formatCurrency(value: string): string {
  const amount = Number(value);
  if (Number.isNaN(amount)) return value;
  return `RM ${amount.toLocaleString("en-MY", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

// For a value already scaled as a percent (e.g. interest_rate_percent):
// "3.0000" -> "3.00%"
export function formatPercent(value: string): string {
  const percent = Number(value);
  if (Number.isNaN(percent)) return value;
  return `${percent.toLocaleString("en-MY", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
}

// For a 0-1 ratio (e.g. residual_value_ratio): "0.5000" -> "50.00%"
export function formatRatioAsPercent(value: string): string {
  const ratio = Number(value);
  if (Number.isNaN(ratio)) return value;
  return `${(ratio * 100).toLocaleString("en-MY", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
}
