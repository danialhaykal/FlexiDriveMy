import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MlModelHistoryPage } from "./MlModelHistoryPage";
import { fetchProductionModel, fetchTrainingRuns } from "../api/ml";
import type { MLTrainingRun, ProductionModelInfo } from "../types/ml";
import { predictionTargetLabel } from "../lib/mlLabels";

// FX-3 (X13): plain target labels instead of audit codes, candidates in words, "Run N" on every run line and a
// "Live" badge only on the run buyers are served.

vi.mock("../api/ml", () => ({
  fetchTrainingRuns: vi.fn(),
  fetchTrainingRun: vi.fn(),
  fetchProductionModel: vi.fn(),
  uploadTrainingDataset: vi.fn(),
  deployTrainingRun: vi.fn(),
}));

function makeRun(overrides: Partial<MLTrainingRun> = {}): MLTrainingRun {
  return {
    id: 1, status: "succeeded", dataset_filename: "resale.csv", row_count: 983, rf_r2: 0.86, rf_mae: 0.51,
    rf_mae_display: "x", rf_best_params: null, gb_r2: 0.87, gb_mae: 0.58, gb_mae_display: "x", mae_unit: "log_price",
    gb_best_params: null, deployed: false, deployed_model_type: "", deploy_eligible: false, candidate_model_type: "",
    rejection_reason: "", error_message: "", known_issue_note: "", created_at: "2026-10-15T09:00:00Z",
    updated_at: "2026-10-15T09:00:00Z", ...overrides,
  };
}

const PRODUCTION: ProductionModelInfo = {
  training_run: 10, model_type: "log_linear", model_type_label: "Log-linear (hedonic)",
  prediction_target: "log_resale_price", prediction_target_label: "Resale price (log scale)", r2_score: 0.9124,
  within_model_r2: 0.7199, mae: 0.1473, mae_display: "typical error ≈ 16% of price", deployed_at: "2026-10-15T10:00:00Z",
  is_serving: true,
};

const RUNS = [
  makeRun({ id: 10, prediction_target: "log_resale_price", prediction_target_label: "Resale price (log scale)",
    deployed: true, deployed_model_type: "log_linear" }),
  makeRun({ id: 8, prediction_target: "value_retention_ratio", prediction_target_label: "Value-retention ratio (C8)" }),
  makeRun({ id: 5, prediction_target: "raw_resale_price", prediction_target_label: "Raw resale price (legacy, pre-C8)",
    deployed: true, deployed_model_type: "random_forest", retired_at: "2026-10-01T00:00:00Z" }),
];

function runLine(id: number): HTMLElement {
  return screen.getByText(`Run ${id}`).closest("li") as HTMLElement;
}

describe("predictionTargetLabel", () => {
  it("names each target plainly and keeps the server's label for an unknown one", () => {
    expect(predictionTargetLabel("log_resale_price", "x")).toBe("Resale price (log scale)");
    expect(predictionTargetLabel("value_retention_ratio", "Value-retention ratio (C8)")).toBe("Value-retention ratio (older runs)");
    expect(predictionTargetLabel("raw_resale_price", "Raw resale price (legacy, pre-C8)")).toBe("Raw resale price (oldest runs)");
    expect(predictionTargetLabel("", "")).toBe("");
    expect(predictionTargetLabel(undefined, "Something new")).toBe("Something new");
  });
});

describe("MlModelHistoryPage FX-3", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(fetchTrainingRuns).mockResolvedValue(RUNS);
  });

  it("shows Run N on every line, plain targets and no audit codes", async () => {
    vi.mocked(fetchProductionModel).mockResolvedValue(PRODUCTION);
    render(<MlModelHistoryPage />);

    expect(await screen.findByText("Run 10")).toBeInTheDocument();
    expect(screen.getByText("Run 8")).toBeInTheDocument();
    expect(screen.getByText("Run 5")).toBeInTheDocument();
    expect(within(runLine(8)).getByText("Value-retention ratio (older runs)")).toBeInTheDocument();
    expect(within(runLine(5)).getByText("Raw resale price (oldest runs)")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/C8/);
  });

  it("names the candidates in words", async () => {
    vi.mocked(fetchProductionModel).mockResolvedValue(PRODUCTION);
    render(<MlModelHistoryPage />);

    const line = (await screen.findByText("Run 10")).closest("li") as HTMLElement;
    for (const name of ["Random forest", "Gradient boosting", "Log-linear"]) {
      expect(within(line).getByRole("rowheader", { name })).toBeInTheDocument();
    }
    expect(within(line).queryByRole("rowheader", { name: "RF" })).not.toBeInTheDocument();
  });

  it("puts Live only on the serving production run", async () => {
    vi.mocked(fetchProductionModel).mockResolvedValue(PRODUCTION);
    render(<MlModelHistoryPage />);
    await screen.findByText("Run 10");

    expect(within(runLine(10)).getByText("Live")).toHaveAttribute("data-tone");
    expect(within(runLine(5)).queryByText("Live")).not.toBeInTheDocument();
    expect(screen.getAllByText("Live")).toHaveLength(1);
  });

  it("shows no Live badge when the production model is not serving", async () => {
    vi.mocked(fetchProductionModel).mockResolvedValue({ ...PRODUCTION, is_serving: false });
    render(<MlModelHistoryPage />);
    await screen.findByText("Run 10");

    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });
});
