import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { MlModelHistoryPage } from "./MlModelHistoryPage";
import { fetchProductionModel, fetchTrainingRuns } from "../api/ml";
import type { MLTrainingRun, ProductionModelInfo } from "../types/ml";

// Run 3 fix batch 5 (F-26): like the Policy Configuration page's test - the ML
// Model Management page's own text carries no developer references (batch codes,
// internal names, use-case codes). Stored reasons are reworded on the server
// (clean_ml_run_texts) and shown as sent; here they are plain.

vi.mock("../api/ml", () => ({
  fetchTrainingRuns: vi.fn(),
  fetchTrainingRun: vi.fn(),
  fetchProductionModel: vi.fn(),
  uploadTrainingDataset: vi.fn(),
  deployTrainingRun: vi.fn(),
}));

const DEVELOPER_TEXT = /CLAUDE|\bUC0\d\d\b|\bF0\d\d\b|\bsprint\b|\bTODO\b|QA audit|\bbatch \d|msrp_proxy|leave-one-out/i;

function run(overrides: Partial<MLTrainingRun>): MLTrainingRun {
  return {
    id: 1, status: "succeeded", dataset_filename: "real_historical_pricing.csv", row_count: 983, rf_r2: 0.86,
    rf_mae: 0.51, rf_mae_display: "typical error ≈ 67% of price", rf_best_params: null, gb_r2: 0.88, gb_mae: 0.59,
    gb_mae_display: "typical error ≈ 80% of price", mae_unit: "log", gb_best_params: null, deployed: false,
    deployed_model_type: "", deploy_eligible: false, candidate_model_type: "", rejection_reason: "",
    error_message: "", known_issue_note: "", created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z",
    ...overrides,
  } as MLTrainingRun;
}

const production: ProductionModelInfo = {
  training_run: 10, model_type: "log_linear", prediction_target: "log_resale_price",
  prediction_target_label: "Resale price (log scale)", r2_score: 0.9124, within_model_r2: 0.7199, mae: 0.1473,
  mae_display: "typical error ≈ 16% of price", deployed_at: "2026-10-16T00:00:00Z", is_serving: true,
};

beforeEach(() => {
  vi.mocked(fetchTrainingRuns).mockResolvedValue([
    run({ id: 8, rejection_reason: "Best validation R² (0.6136 from Gradient Boosting) is below the required 0.80 threshold; keeping the current production model." }),
    run({ id: 10, deployed: true, deployed_model_type: "log_linear", candidate_model_type: "log_linear" }),
  ]);
  vi.mocked(fetchProductionModel).mockResolvedValue(production);
});

describe("ML Model Management page", () => {
  it("shows no developer references in its own text", async () => {
    const { container } = render(<MlModelHistoryPage />);
    await screen.findByText("R² trend");

    expect(container.textContent).not.toMatch(DEVELOPER_TEXT);
    expect(screen.getByText(/Random Forest, Gradient Boosting and log-linear validation R² across every recorded run/))
      .toBeInTheDocument();
  });
});
