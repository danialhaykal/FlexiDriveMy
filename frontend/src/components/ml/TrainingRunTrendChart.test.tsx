import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { buildChartPoints, buildChartSeries, TrainingRunTrendChart } from "./TrainingRunTrendChart";
import type { MLTrainingRun } from "../../types/ml";

const RAW = "raw_resale_price__";

function makeRun(overrides: Partial<MLTrainingRun> = {}): MLTrainingRun {
  return {
    id: 1,
    status: "succeeded",
    dataset_filename: "seed.csv",
    row_count: 100,
    prediction_target: "raw_resale_price",
    prediction_target_label: "Raw resale price (legacy, pre-C8)",
    rf_r2: 0.75,
    rf_mae: 5000,
    rf_mae_display: "RM 5,000.00",
    rf_best_params: null,
    gb_r2: 0.7,
    gb_mae: 5200,
    gb_mae_display: "RM 5,200.00",
    mae_unit: "rm",
    gb_best_params: null,
    deployed: false,
    deployed_model_type: "",
    deploy_eligible: false,
    candidate_model_type: "",
    rejection_reason: "",
    error_message: "",
    known_issue_note: "",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

// Newest-first, exactly as GET /api/ml/training-runs/ returns it.
const runs: MLTrainingRun[] = [
  makeRun({
    id: 4,
    created_at: "2026-04-01T00:00:00Z",
    rf_r2: 0.89,
    gb_r2: 0.82,
    deployed: true,
    deployed_model_type: "random_forest",
    known_issue_note:
      "This run's msrp_proxy feature was computed without leave-one-out exclusion, inflating R2.",
  }),
  makeRun({
    id: 3,
    created_at: "2026-03-01T00:00:00Z",
    status: "failed",
    prediction_target: "",
    prediction_target_label: "",
    rf_r2: null,
    gb_r2: null,
    rf_mae: null,
    gb_mae: null,
    rf_mae_display: null,
    gb_mae_display: null,
    mae_unit: null,
    error_message: "Training crashed: out of memory.",
  }),
  makeRun({ id: 2, created_at: "2026-02-01T00:00:00Z", rf_r2: 0.81, gb_r2: 0.78 }),
  makeRun({ id: 1, created_at: "2026-01-01T00:00:00Z", rf_r2: 0.6, gb_r2: 0.55 }),
];

describe("buildChartPoints", () => {
  it("reverses newest-first runs into chronological (oldest-first) order", () => {
    const points = buildChartPoints(runs);
    expect(points).toHaveLength(4);
    expect(points[0][`${RAW}rf`]).toBe(0.6); // oldest run (id 1, Jan)
    expect(points[3][`${RAW}rf`]).toBe(0.89); // newest run (id 4, Apr)
  });

  it("leaves a failed run's R2 as undefined, never plotted as zero", () => {
    const points = buildChartPoints(runs);
    const failedRunPoint = points[2]; // id 3, Mar, chronologically third
    expect(failedRunPoint[`${RAW}rf`]).toBeUndefined();
    expect(failedRunPoint[`${RAW}gb`]).toBeUndefined();
  });

  it("flags only the estimator that actually deployed, on the correct point", () => {
    const points = buildChartPoints(runs);
    const deployedRunPoint = points[3]; // id 4, Apr - deployed random_forest
    expect(deployedRunPoint[`${RAW}rf_deployed`]).toBe(true);
    expect(deployedRunPoint[`${RAW}gb_deployed`]).toBe(false); // GB wasn't the deployed estimator

    const nonDeployedRunPoint = points[0];
    expect(nonDeployedRunPoint[`${RAW}rf_deployed`]).toBe(false);
    expect(nonDeployedRunPoint[`${RAW}gb_deployed`]).toBe(false);
  });

  // ML batch 1: a run's R² goes only into its own target's series.
  it("puts each run's R² only in its own target's series", () => {
    const mixed = [
      makeRun({ id: 9, created_at: "2026-10-15T00:00:00Z", prediction_target: "log_resale_price",
        prediction_target_label: "Resale price (log scale)", rf_r2: 0.8673, gb_r2: 0.8789 }),
      makeRun({ id: 8, created_at: "2026-10-05T00:00:00Z", prediction_target: "value_retention_ratio",
        prediction_target_label: "Value-retention ratio (C8)", rf_r2: 0.5612, gb_r2: 0.6136 }),
    ];

    const [ratioPoint, logPoint] = buildChartPoints(mixed);

    expect(ratioPoint["value_retention_ratio__gb"]).toBe(0.6136);
    expect(ratioPoint["log_resale_price__gb"]).toBeUndefined();
    expect(logPoint["log_resale_price__gb"]).toBe(0.8789);
    expect(logPoint["value_retention_ratio__gb"]).toBeUndefined();
  });
});

describe("buildChartSeries", () => {
  it("makes one Random Forest and one Gradient Boosting series per target, named after it", () => {
    const mixed = [
      makeRun({ id: 9, prediction_target: "log_resale_price", prediction_target_label: "Resale price (log scale)" }),
      makeRun({ id: 8, prediction_target: "value_retention_ratio", prediction_target_label: "Value-retention ratio (C8)" }),
      makeRun({ id: 7, status: "failed", prediction_target: "", prediction_target_label: "" }),
      makeRun({ id: 6, prediction_target: "value_retention_ratio", prediction_target_label: "Value-retention ratio (C8)" }),
    ];

    expect(buildChartSeries(mixed).map((s) => s.name)).toEqual([
      "Random Forest R² - Value-retention ratio (older runs)",
      "Gradient Boosting R² - Value-retention ratio (older runs)",
      "Random Forest R² - Resale price (log scale)",
      "Gradient Boosting R² - Resale price (log scale)",
    ]);
  });

  it("carries known_issue_note through only for the annotated run", () => {
    const points = buildChartPoints(runs);
    const annotatedRunPoint = points[3]; // id 4, Apr
    expect(annotatedRunPoint.known_issue_note).toBe(
      "This run's msrp_proxy feature was computed without leave-one-out exclusion, inflating R2.",
    );

    const unannotatedRunPoints = [points[0], points[1], points[2]];
    for (const point of unannotatedRunPoints) {
      expect(point.known_issue_note).toBe("");
    }
  });
});

describe("TrainingRunTrendChart", () => {
  it("renders both series and the deployed point's marker without crashing", () => {
    const { container } = render(<TrainingRunTrendChart runs={runs} />);

    expect(screen.getByText("Random Forest R² - Raw resale price (oldest runs)")).toBeInTheDocument();
    expect(screen.getByText("Gradient Boosting R² - Raw resale price (oldest runs)")).toBeInTheDocument();
    expect(container.querySelectorAll("path.recharts-line-curve")).toHaveLength(2);
    expect(container.querySelector('circle[data-deployed="true"]')).not.toBeNull();
    // One target only: nothing to warn about.
    expect(screen.queryByText(/not comparable/)).not.toBeInTheDocument();
  });

  it("draws a pair of lines per target and says R² across targets is not comparable", () => {
    const mixed = [
      makeRun({ id: 9, created_at: "2026-10-15T00:00:00Z", prediction_target: "log_resale_price",
        prediction_target_label: "Resale price (log scale)", rf_r2: 0.8673, gb_r2: 0.8789 }),
      ...runs,
    ];
    const { container } = render(<TrainingRunTrendChart runs={mixed} />);

    expect(container.querySelectorAll("path.recharts-line-curve")).toHaveLength(4);
    expect(screen.getByText("Gradient Boosting R² - Resale price (log scale)")).toBeInTheDocument();
    expect(
      screen.getByText(
        "R² from different prediction targets is not comparable: each set of lines measures its own target, so compare runs only along the same line.",
      ),
    ).toBeInTheDocument();
  });

  // ML batch 2: the log-linear candidate is a third line for a target whose runs recorded it.
  it("adds a log-linear line only where a run recorded one, and marks it when it deployed", () => {
    const withLogLinear = [
      makeRun({ id: 10, created_at: "2026-10-15T09:00:00Z", prediction_target: "log_resale_price",
        prediction_target_label: "Resale price (log scale)", rf_r2: 0.8603, gb_r2: 0.8776, ll_r2: 0.9124,
        deployed: true, deployed_model_type: "log_linear" }),
      ...runs,
    ];

    const series = buildChartSeries(withLogLinear);
    expect(series.map((s) => s.name)).toEqual([
      "Random Forest R² - Raw resale price (oldest runs)",
      "Gradient Boosting R² - Raw resale price (oldest runs)",
      "Random Forest R² - Resale price (log scale)",
      "Gradient Boosting R² - Resale price (log scale)",
      "Log-linear R² - Resale price (log scale)",
    ]);
    const newest = buildChartPoints(withLogLinear).at(-1)!;
    expect(newest["log_resale_price__ll"]).toBe(0.9124);
    expect(newest["log_resale_price__ll_deployed"]).toBe(true);
    expect(newest["log_resale_price__gb_deployed"]).toBe(false);

    const { container } = render(<TrainingRunTrendChart runs={withLogLinear} />);
    expect(container.querySelectorAll("path.recharts-line-curve")).toHaveLength(5);
    expect(screen.getByText("Log-linear R² - Resale price (log scale)")).toBeInTheDocument();
  });

  it("renders a known-issue ring only around the annotated run's points", () => {
    const { container } = render(<TrainingRunTrendChart runs={runs} />);

    // id 4 has known_issue_note set on both its RF and GB points (the same
    // underlying run affects both estimators' training data identically).
    expect(container.querySelectorAll('circle[data-known-issue="true"]')).toHaveLength(2);
  });

  it("renders no known-issue ring at all when nothing is annotated", () => {
    const unannotatedRuns = runs.map((run) => ({ ...run, known_issue_note: "" }));
    const { container } = render(<TrainingRunTrendChart runs={unannotatedRuns} />);

    expect(container.querySelectorAll('circle[data-known-issue="true"]')).toHaveLength(0);
  });
});

describe("TrainingRunTrendChart legend (redesign UI-6b)", () => {
  it("groups the legend by prediction target, short names on screen and full names for screen readers", () => {
    const runs = [
      makeRun({ id: 9, prediction_target: "log_resale_price", prediction_target_label: "Resale price (log scale)", ll_r2: 0.91 }),
      makeRun({ id: 8, prediction_target: "value_retention_ratio", prediction_target_label: "Value-retention ratio (C8)" }),
    ];
    render(<TrainingRunTrendChart runs={runs} />);

    const legend = screen.getByRole("list", { name: "Chart legend" });
    const groups = within(legend).getAllByRole("listitem");
    expect(groups[0]).toHaveTextContent(/^Value-retention ratio \(older runs\)/);
    expect(groups[1]).toHaveTextContent(/^Resale price \(log scale\)/);
    expect(within(groups[1]).getByText("Log-linear R² - Resale price (log scale)")).toHaveClass("sr-only");
    expect(within(groups[2]).getByText("Deployment threshold (0.80)")).toBeInTheDocument();
  });
});
