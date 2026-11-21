import {
  Legend,
  PolarAngleAxis,
  PolarGrid,
  PolarRadiusAxis,
  Radar,
  RadarChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import { PATHWAY_LABELS } from "../../types/scoring";
import type { PathwayKey } from "../../types/scoring";
import type { RiskRadarPathwayScores } from "../../types/depreciation";

// UC006 step 7's 3-axis risk comparison radar. Same recharts conventions
// as NegativeEquityChart.tsx (CSS-variable colors, a data-export-chart
// hook, an accessible Legend, numbers converted from the API's decimal
// strings only at render time, never recomputed). One Radar line per
// pathway `risk_radar` actually includes; a pathway missing its own
// config is listed as plain text below instead of an empty/zeroed line.
//
// Usage: <RiskRadarChart radar={report.risk_radar} unavailable={report.radar_unavailable} />

interface RiskRadarChartProps {
  // Live-walkthrough finding: both `| undefined` for real - a scenario
  // saved before Batch 6C added these fields has neither key at all in
  // its stored payload (SavedScenarioPage.tsx renders whatever was
  // actually saved, unchanged).
  radar: Partial<Record<PathwayKey, RiskRadarPathwayScores>> | undefined;
  unavailable: Partial<Record<PathwayKey, string>> | undefined;
}

const CRITERION_LABELS: { key: keyof RiskRadarPathwayScores; label: string }[] = [
  { key: "upfront_cash_preservation", label: "Upfront Cash Preservation" },
  { key: "maintenance_protection", label: "Maintenance Protection" },
  { key: "ownership_equity", label: "Ownership Equity" },
];

// Redesign UI-3: the pathway colours used on every card and badge (index.css
// pathway tokens). Not the PDF chart - NegativeEquityChart keeps its own colours.
const PATHWAY_COLORS: Record<PathwayKey, string> = {
  hire_purchase: "var(--color-pathway-hp)",
  gfv_leasing: "var(--color-pathway-gfv)",
  subscription: "var(--color-pathway-sub)",
};

// Redesign UI-3: each axis label on two lines ("Maintenance" / "Protection"), so the
// longest label fits a half-width card and a phone instead of running off the edge.
interface RadarAxisTickProps {
  x?: number | string;
  y?: number | string;
  textAnchor?: string;
  payload?: { value?: string | number };
}

function RadarAxisTick({ x = 0, y = 0, textAnchor = "middle", payload }: RadarAxisTickProps) {
  const words = String(payload?.value ?? "").split(" ");
  const half = Math.ceil(words.length / 2);
  const lines = [words.slice(0, half).join(" "), words.slice(half).join(" ")].filter(Boolean);
  return (
    <text x={x} y={y} textAnchor={textAnchor as "start" | "middle" | "end"} fontSize={12} fill="var(--color-ink-muted)">
      {lines.map((line, index) => (
        <tspan key={line} x={x} dy={index === 0 ? (lines.length > 1 ? "-0.35em" : "0.35em") : "1.2em"}>
          {line}
        </tspan>
      ))}
    </text>
  );
}

export function RiskRadarChart({ radar: radarProp, unavailable: unavailableProp }: RiskRadarChartProps) {
  const radar = radarProp ?? {};
  const unavailable = unavailableProp ?? {};
  const availablePathways = (Object.keys(radar) as PathwayKey[]).filter((pathway) => radar[pathway]);

  const data = CRITERION_LABELS.map(({ key, label }) => {
    const point: Record<string, number | string> = { criterion: label };
    for (const pathway of availablePathways) {
      point[pathway] = Number(radar[pathway]?.[key] ?? 0);
    }
    return point;
  });

  return (
    <div>
      <div className="h-[26rem] w-full" data-export-chart="tco-risk-radar">
        <ResponsiveContainer width="100%" height="100%">
          {/* Wide side margins and a 68% radius keep the longest axis label
              ("Maintenance Protection") inside a half-width card. */}
          <RadarChart data={data} outerRadius="68%" margin={{ top: 16, right: 56, bottom: 8, left: 56 }}>
            <PolarGrid stroke="var(--color-border)" />
            <PolarAngleAxis dataKey="criterion" tick={RadarAxisTick} />
            <PolarRadiusAxis domain={[0, 1]} tick={{ fontSize: 11 }} />
            <Tooltip />
            {/* Run 3 fix batch 5 (F-28): labels in ink (WCAG AA), not the series colour -
                "GFV Leasing" in amber was 3.20:1 and "Subscription" in green 3.65:1.
                Redesign UI-6b: a round pathway dot beside each label (the same dots as
                the pathway cards). */}
            <Legend
              iconType="circle"
              iconSize={10}
              wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
              formatter={(value) => <span style={{ color: "var(--color-ink)" }}>{value}</span>}
            />
            {/* Redesign UI-6b: a clearer outline and a light fill per pathway, with its points marked. */}
            {availablePathways.map((pathway) => (
              <Radar
                key={pathway}
                name={PATHWAY_LABELS[pathway]}
                dataKey={pathway}
                stroke={PATHWAY_COLORS[pathway]}
                strokeWidth={2}
                fill={PATHWAY_COLORS[pathway]}
                fillOpacity={0.12}
                dot={{ r: 3, fill: PATHWAY_COLORS[pathway], strokeWidth: 0 }}
              />
            ))}
          </RadarChart>
        </ResponsiveContainer>
      </div>
      {Object.keys(unavailable).length > 0 && (
        <ul className="mt-3 flex flex-col gap-1 text-small text-ink-muted">
          {(Object.keys(unavailable) as PathwayKey[]).map((pathway) => (
            <li key={pathway}>
              <span className="font-medium text-ink">{PATHWAY_LABELS[pathway]}:</span>{" "}
              {unavailable[pathway]}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
