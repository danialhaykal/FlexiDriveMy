import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { formatCurrency } from "../../lib/formatCurrency";
import type { CumulativeCashFlowPoint } from "../../types/depreciation";

// UC006 step 6's cumulative cash flow chart - the HP pathway's running
// cash outlay over the 60-month horizon. Same conventions as
// NegativeEquityChart.tsx: compact-currency Y-axis ticks, full currency
// in the tooltip, numbers converted from the API's decimal strings only
// at render time.

function formatCompactCurrency(value: number): string {
  const absValue = Math.abs(value);
  if (absValue >= 1_000_000) return `RM ${(value / 1_000_000).toFixed(1)}M`;
  if (absValue >= 1_000) return `RM ${(value / 1_000).toFixed(0)}k`;
  return `RM ${value.toFixed(0)}`;
}

interface CumulativeCashFlowChartProps {
  // Live-walkthrough finding: `| undefined` for real - a scenario saved
  // before Batch 6C added this field has no `cumulative_cash_flow` key
  // at all in its stored payload (SavedScenarioPage.tsx renders whatever
  // was actually saved, unchanged).
  cumulativeCashFlow: CumulativeCashFlowPoint[] | undefined;
}

// The Hire Purchase pathway colour (index.css pathway token).
const FILL_COLOR = "var(--color-pathway-hp)";

export function CumulativeCashFlowChart({
  cumulativeCashFlow: cumulativeCashFlowProp,
}: CumulativeCashFlowChartProps) {
  const cumulativeCashFlow = cumulativeCashFlowProp ?? [];
  const data = cumulativeCashFlow.map((point) => ({
    month: point.month,
    cumulativeCashOutflow: Number(point.cumulative_cash_outflow),
  }));

  return (
    <div className="h-80 w-full" data-export-chart="tco-cumulative-cash-flow">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
          <XAxis
            dataKey="month"
            tickFormatter={(month: number) => `${month}mo`}
            stroke="var(--color-ink-muted)"
            fontSize={12}
          />
          {/* Redesign UI-3: 80 px wide (was 64), so a tick such as "RM 255k" stays on
              one line instead of wrapping to "RM" / "255k". */}
          <YAxis
            tickFormatter={formatCompactCurrency}
            stroke="var(--color-ink-muted)"
            fontSize={12}
            width={80}
          />
          <Tooltip
            formatter={(value) => formatCurrency(String(value))}
            labelFormatter={(month) => `Month ${month}`}
          />
          <Area
            type="monotone"
            dataKey="cumulativeCashOutflow"
            name="Cumulative cash outflow"
            stroke={FILL_COLOR}
            fill={FILL_COLOR}
            fillOpacity={0.15}
            strokeWidth={2}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
