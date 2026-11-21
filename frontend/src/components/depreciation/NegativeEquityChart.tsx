import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatCurrency } from "../../lib/formatCurrency";
import type { MonthlyForecastPoint } from "../../types/depreciation";

// QA audit L17: the Y-axis previously used formatCurrency's full
// "RM 400,000.00" form for every tick - too wide for a fixed-width axis
// at a readable font size, so it wrapped/got clipped. A compact form
// here is axis-label-only (the Tooltip below still shows the exact,
// unrounded formatCurrency figure on hover) - never a recomputed
// financial value, purely a shorter DISPLAY of the same number already
// returned by the API.
function formatCompactCurrency(value: number): string {
  const absValue = Math.abs(value);
  if (absValue >= 1_000_000) return `RM ${(value / 1_000_000).toFixed(1)}M`;
  if (absValue >= 1_000) return `RM ${(value / 1_000).toFixed(0)}k`;
  return `RM ${value.toFixed(0)}`;
}

// UC006 step 7 / 9.4-9.5: "Remaining Loan vs Actual Car Value" chart.
// Values are converted from the API's decimal strings to numbers only
// because Recharts' plotting math requires numbers to compute pixel
// coordinates - each value is exactly what the API returned, nothing is
// recomputed (the same reasoning formatCurrency already follows).
//
// Usage: <NegativeEquityChart monthlyForecast={report.monthly_forecast}
//   crossoverMonth={report.negative_equity_crossover_month}
//   shortfallAmount={report.negative_equity_shortfall_amount} />

interface NegativeEquityChartProps {
  monthlyForecast: MonthlyForecastPoint[];
  crossoverMonth: number | null;
  shortfallAmount: string | null;
}

// Wide enough for the longest compact tick ("RM 1.2M", "RM 280k") at 12px on one line.
export const Y_AXIS_WIDTH = 80;

const RESALE_COLOR = "var(--color-primary-600)";
const BALANCE_COLOR = "var(--color-danger-600)";

export function NegativeEquityChart({
  monthlyForecast,
  crossoverMonth,
  shortfallAmount,
}: NegativeEquityChartProps) {
  const data = monthlyForecast.map((point) => ({
    month: point.month,
    resaleValue: Number(point.predicted_resale_value),
    outstandingBalance: Number(point.hp_outstanding_balance),
  }));

  return (
    <div>
      {/* QA audit M16: a stable, query-able hook so ExportPdfButton can
          grab this chart's live <svg> at export time - only present while
          the TCO tab is actually mounted (Tabs.Panel unmounts inactive
          panels), which is exactly the "chart available" signal the
          export flow needs. */}
      <div className="h-80 w-full" data-export-chart="tco-negative-equity">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
            <XAxis
              dataKey="month"
              tickFormatter={(month: number) => `${month}mo`}
              stroke="var(--color-ink-muted)"
              fontSize={12}
            />
            <YAxis
              tickFormatter={formatCompactCurrency}
              stroke="var(--color-ink-muted)"
              fontSize={12}
              // Run 2 fix batch 3: 64 was a little narrow for "RM 280k" (and
              // "RM 1.2M"), which wrapped onto two lines on screen and in the PDF.
              width={Y_AXIS_WIDTH}
            />
            <Tooltip
              formatter={(value) => formatCurrency(String(value))}
              labelFormatter={(month) => `Month ${month}`}
            />
            {/* QA audit L17: the two lines were previously told apart by
                color only - a real accessibility issue (same pattern as
                L16's DSR gauge fix) for anyone who can't rely on color
                alone. */}
            <Legend wrapperStyle={{ fontSize: 12 }} />
            <Line
              type="monotone"
              dataKey="resaleValue"
              name="Predicted resale value"
              stroke={RESALE_COLOR}
              strokeWidth={2}
              dot={false}
            />
            <Line
              type="monotone"
              dataKey="outstandingBalance"
              name="Amount to settle (estimate)"
              stroke={BALANCE_COLOR}
              strokeWidth={2}
              dot={false}
            />
            {crossoverMonth !== null && (
              <ReferenceLine
                x={crossoverMonth}
                stroke="var(--color-danger-600)"
                strokeDasharray="4 4"
                label={{
                  value: "Negative equity",
                  position: "insideTopLeft",
                  fill: "var(--color-danger-700)",
                  fontSize: 12,
                }}
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>
      {/* Run 1: the balance is now the reducing-balance settlement amount
          (apps.comparisons.formulas.settlement_balance), computed server-side. */}
      <p className="mt-3 text-caption text-ink-muted">
        The remaining loan balance is an estimate of the amount needed to settle the loan, using the
        reducing-balance method that the Hire-Purchase (Amendment) Act 2026 requires for new loans. Your
        lender's settlement letter is the final figure.
      </p>
      {crossoverMonth !== null && shortfallAmount !== null && (
        <p className="mt-3 rounded-md border border-danger-200 bg-danger-50 p-3 text-small text-danger-700">
          Negative equity begins at month {crossoverMonth}: predicted resale value falls{" "}
          <span className="font-medium tabular-nums">{formatCurrency(shortfallAmount)}</span> short
          of the outstanding loan balance.
        </p>
      )}
    </div>
  );
}
