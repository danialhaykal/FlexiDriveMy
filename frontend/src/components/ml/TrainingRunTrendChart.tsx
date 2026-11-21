import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { DotItemDotProps, TooltipContentProps } from "recharts";
import type { MLTrainingRun } from "../../types/ml";
import { formatAdminDateTime } from "../../lib/formatAdminDate";
import { predictionTargetLabel } from "../../lib/mlLabels";

// F012 / Sprint 13 - the R2 trend across every real past training run
// (apps/ml/models.py::MLTrainingRun), the same convention
// NegativeEquityChart.tsx already established: ResponsiveContainer +
// LineChart, design-token colors, CartesianGrid, a ReferenceLine for a
// threshold. One y-axis only (R2, 0-1) - MAE is a different scale and
// deliberately left off this chart (see the runs table for MAE instead).
//
// Usage: <TrainingRunTrendChart runs={runs} /> where `runs` is exactly
// what GET /api/ml/training-runs/ returned (newest-first) - this
// component reverses to chronological order itself for plotting.

//
// ML batch 1: R² measured on different prediction targets (raw price,
// value-retention ratio, log resale price) describes different quantities and
// is not comparable, so every target gets its own set of lines (Random
// Forest and Gradient Boosting, plus - ML batch 2 - the log-linear (hedonic)
// candidate where a run recorded one), named in the legend - never one line
// running across targets.

interface TrainingRunTrendChartProps {
  runs: MLTrainingRun[];
}

type Estimator = "rf" | "gb" | "ll";

export interface TrainingRunSeries {
  // `${target}__${estimator}` - the point key holding this series' R².
  key: string;
  target: string;
  // The target's own label ("Resale price (log scale)"), for the grouped legend.
  targetName: string;
  estimator: Estimator;
  name: string;
}

export interface TrainingRunChartPoint {
  label: string;
  // Sprint 13 addendum - a human-confirmed, manually-set annotation
  // (blank for every run except one that's actually been documented, e.g.
  // "this run's metrics shouldn't be trusted"). Never auto-detected here.
  known_issue_note: string;
  // Per series key: the R² (undefined - never 0 - when this run belongs to
  // another target or recorded none), and `${key}_deployed`.
  [seriesKey: string]: number | string | boolean | undefined;
}

const ESTIMATOR_NAME: Record<Estimator, string> = {
  rf: "Random Forest R²",
  gb: "Gradient Boosting R²",
  ll: "Log-linear R²",
};

const ESTIMATOR_MODEL_TYPE: Record<Estimator, string> = {
  rf: "random_forest",
  gb: "gradient_boosting",
  ll: "log_linear",
};

function runR2(run: MLTrainingRun, estimator: Estimator): number | undefined {
  const value = estimator === "rf" ? run.rf_r2 : estimator === "gb" ? run.gb_r2 : run.ll_r2;
  return value ?? undefined;
}

function seriesKey(target: string, estimator: Estimator): string {
  return `${target}__${estimator}`;
}

// One RF and one GB series per prediction target present in `runs`, in the
// order the targets first appear chronologically, plus a log-linear series for
// a target where any run recorded a log-linear R². A run with no target
// (failed, no metrics) belongs to no series.
export function buildChartSeries(runs: MLTrainingRun[]): TrainingRunSeries[] {
  const series: TrainingRunSeries[] = [];
  const seen = new Set<string>();
  for (const run of [...runs].reverse()) {
    const target = run.prediction_target ?? "";
    if (!target || seen.has(target)) continue;
    seen.add(target);
    // FX-3 (X13): plain target names (no audit codes).
    const targetName = predictionTargetLabel(run.prediction_target, run.prediction_target_label) || target;
    const hasLogLinear = runs.some((r) => r.prediction_target === target && r.ll_r2 != null);
    const estimators: Estimator[] = hasLogLinear ? ["rf", "gb", "ll"] : ["rf", "gb"];
    for (const estimator of estimators) {
      series.push({
        key: seriesKey(target, estimator),
        target,
        targetName,
        estimator,
        name: `${ESTIMATOR_NAME[estimator]} - ${targetName}`,
      });
    }
  }
  return series;
}

// apps.ml.models.R2_DEPLOYMENT_THRESHOLD, mirrored - a fixed constant
// from the project spec's own deployment gate, not user data fetched from the
// API.
const R2_DEPLOYMENT_THRESHOLD = 0.8;

// Two fixed, distinct, non-status colors for RF vs GB - deliberately NOT
// positive/warning/danger, which already carry a "something's
// wrong"/"on track" status meaning elsewhere in this codebase (Badge
// tones, NegativeEquityChart's own danger-colored balance line) and
// would misleadingly suggest one *model type* is inherently the "good"
// or "bad" one, when the project spec's own rule is "deploy whichever has the
// higher validation R2" - neither is fixed as the preferred candidate.
// RF uses this design system's one existing accent (primary/indigo). GB
// uses Tailwind's teal - a raw default-palette color this codebase's
// index.css imports via `@import "tailwindcss"` but has never aliased
// into any semantic meaning, so it carries no status connotation at all;
// genuinely neutral/categorical, and visually distinct from both indigo
// and the reserved positive/warning/danger family.
const RF_COLOR = "var(--color-primary-600)";
const GB_COLOR = "var(--color-teal-600)";
// ML batch 2: the log-linear candidate, another neutral categorical colour.
const LL_COLOR = "var(--color-violet-600)";
const ESTIMATOR_COLOR: Record<Estimator, string> = { rf: RF_COLOR, gb: GB_COLOR, ll: LL_COLOR };
const THRESHOLD_COLOR = "var(--color-ink-muted)";

function formatRunDate(value: string): string {
  // Cosmetic: date-only (no time) meant two runs on the SAME day got the
  // identical x-axis label, rendered twice adjacent to each other with
  // no way to tell which point was which. Including the time makes every
  // run's label distinct, which is also just genuinely more informative
  // for an admin comparing same-day retrains.
  // FX-3 (X13): the one admin date format.
  return formatAdminDateTime(value);
}

// Pure, exported separately from the chart so it's directly unit-testable
// without needing to render Recharts at all - see
// TrainingRunTrendChart.test.tsx.
export function buildChartPoints(runs: MLTrainingRun[]): TrainingRunChartPoint[] {
  const chronological = [...runs].reverse();
  return chronological.map((run) => {
    const point: TrainingRunChartPoint = {
      label: formatRunDate(run.created_at),
      known_issue_note: run.known_issue_note,
    };
    const target = run.prediction_target ?? "";
    if (target) {
      for (const estimator of ["rf", "gb", "ll"] as const) {
        const key = seriesKey(target, estimator);
        point[key] = runR2(run, estimator);
        point[`${key}_deployed`] = run.deployed && run.deployed_model_type === ESTIMATOR_MODEL_TYPE[estimator];
      }
    }
    return point;
  });
}

// Solid for the first target drawn, then dashed patterns, so two targets'
// lines never look like one; RF/GB keep their colours.
const TARGET_DASHES = [undefined, "6 3", "2 3", "8 3 2 3"];

// The reserved `warning` token is deliberately used here (unlike RF/GB's
// own fixed, non-status colors above) - a known_issue_note genuinely IS
// "something's wrong with this specific data point", the same status
// meaning `warning` already carries everywhere else in this codebase.
const KNOWN_ISSUE_RING_COLOR = "var(--color-warning-600)";

function makeDotRenderer(color: string, deployedKey: string) {
  function TrainingRunDot(props: DotItemDotProps) {
    const { cx, cy, value, payload } = props;
    if (value === null || value === undefined || cx === undefined || cy === undefined) {
      return <g />;
    }
    const point = payload as TrainingRunChartPoint;
    const isDeployed = Boolean(point[deployedKey]);
    const hasKnownIssue = Boolean(point.known_issue_note);
    const dotRadius = isDeployed ? 7 : 3;
    return (
      <g>
        {hasKnownIssue && (
          <circle
            cx={cx}
            cy={cy}
            r={dotRadius + 4}
            fill="none"
            stroke={KNOWN_ISSUE_RING_COLOR}
            strokeWidth={2}
            data-known-issue="true"
          />
        )}
        <circle
          cx={cx}
          cy={cy}
          r={dotRadius}
          fill={isDeployed ? color : "var(--color-surface)"}
          stroke={color}
          strokeWidth={2}
          data-deployed={isDeployed}
        />
      </g>
    );
  }
  return TrainingRunDot;
}

// Extends Recharts' own Tooltip (the same mechanism NegativeEquityChart.tsx
// uses) with one extra line when the hovered point has a known_issue_note -
// reusing the existing hover mechanism rather than inventing a new one.
function ChartTooltip({ active, payload, label }: TooltipContentProps) {
  if (!active || !payload || payload.length === 0) return null;
  const point = payload[0].payload as TrainingRunChartPoint;
  return (
    <div className="rounded-md border border-border bg-surface p-3 text-small shadow-sm">
      <p className="font-medium text-ink">{label}</p>
      {payload.map((entry) => (
        <p key={String(entry.name)} style={{ color: entry.color }}>
          {entry.name}: {typeof entry.value === "number" ? entry.value.toFixed(4) : entry.value}
        </p>
      ))}
      {point.known_issue_note && (
        <p className="mt-2 max-w-xs border-t border-warning-200 pt-2 text-caption text-warning-700">
          {point.known_issue_note}
        </p>
      )}
    </div>
  );
}

export function TrainingRunTrendChart({ runs }: TrainingRunTrendChartProps) {
  const data = buildChartPoints(runs);
  const series = buildChartSeries(runs);
  const targets = [...new Set(series.map((s) => s.target))];

  return (
    <div>
      <div className="h-96 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
            <XAxis dataKey="label" stroke="var(--color-ink-muted)" fontSize={12} />
            <YAxis domain={[0, 1]} stroke="var(--color-ink-muted)" fontSize={12} />
            <Tooltip content={ChartTooltip} />
            <ReferenceLine
              y={R2_DEPLOYMENT_THRESHOLD}
              stroke={THRESHOLD_COLOR}
              strokeDasharray="4 4"
              label={{
                value: "Deployment threshold (0.80)",
                position: "insideTopLeft",
                fill: THRESHOLD_COLOR,
                fontSize: 12,
              }}
            />
            {/* A series' line joins only its own target's runs: a run of another
                target (or a failed run, which has no target) is not a gap in it. */}
            {series.map((s) => {
              const color = ESTIMATOR_COLOR[s.estimator];
              return (
                <Line
                  key={s.key}
                  type="monotone"
                  dataKey={s.key}
                  name={s.name}
                  stroke={color}
                  strokeWidth={2}
                  strokeDasharray={TARGET_DASHES[targets.indexOf(s.target) % TARGET_DASHES.length]}
                  dot={makeDotRenderer(color, `${s.key}_deployed`)}
                  connectNulls
                />
              );
            })}
          </LineChart>
        </ResponsiveContainer>
      </div>
      {/* Redesign UI-6b: the legend grouped by prediction target - one line per
          target, each series as a coloured line key (solid or dashed, as drawn)
          with its short name; its full name ("Random Forest R² - Resale price (log
          scale)") is what a screen reader hears. Labels in ink (Run 1 fix batch 5,
          M3: the series colours themselves are too light for text). */}
      <ul aria-label="Chart legend" className="mt-3 flex flex-col gap-2">
        {targets.map((target, index) => {
          const targetSeries = series.filter((s) => s.target === target);
          const dash = TARGET_DASHES[index % TARGET_DASHES.length];
          return (
            <li key={target} className="flex flex-wrap items-center gap-x-4 gap-y-1 text-caption text-ink">
              <span className="font-semibold">{targetSeries[0]?.targetName}</span>
              {targetSeries.map((s) => (
                <span key={s.key} className="inline-flex items-center gap-1.5">
                  <svg width="28" height="10" aria-hidden="true" className="shrink-0">
                    <line x1="1" y1="5" x2="27" y2="5" stroke={ESTIMATOR_COLOR[s.estimator]} strokeWidth="2.5" strokeDasharray={dash} />
                  </svg>
                  <span aria-hidden="true">{ESTIMATOR_NAME[s.estimator]}</span>
                  <span className="sr-only">{s.name}</span>
                </span>
              ))}
            </li>
          );
        })}
        <li className="flex flex-wrap items-center gap-x-4 gap-y-1 text-caption text-ink-muted">
          <span className="inline-flex items-center gap-1.5">
            <svg width="16" height="16" aria-hidden="true" className="shrink-0">
              <circle cx="8" cy="8" r="6" fill="var(--color-ink-muted)" />
            </svg>
            Filled dot: the deployed model
          </span>
          <span className="inline-flex items-center gap-1.5">
            <svg width="28" height="10" aria-hidden="true" className="shrink-0">
              <line x1="1" y1="5" x2="27" y2="5" stroke={THRESHOLD_COLOR} strokeWidth="1.5" strokeDasharray="4 4" />
            </svg>
            Deployment threshold (0.80)
          </span>
        </li>
      </ul>
      {targets.length > 1 && (
        <p className="mt-2 text-caption text-ink-muted">
          R² from different prediction targets is not comparable: each set of lines measures its own
          target, so compare runs only along the same line.
        </p>
      )}
    </div>
  );
}

