import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MlModelHistoryPage } from "./MlModelHistoryPage";
import {
  deployTrainingRun,
  fetchProductionModel,
  fetchTrainingRun,
  fetchTrainingRuns,
  uploadTrainingDataset,
} from "../api/ml";
import type { MLTrainingRun, ProductionModelInfo } from "../types/ml";

vi.mock("../api/ml", () => ({
  fetchTrainingRuns: vi.fn(),
  fetchTrainingRun: vi.fn(),
  fetchProductionModel: vi.fn(),
  uploadTrainingDataset: vi.fn(),
  deployTrainingRun: vi.fn(),
}));

const mockedFetchTrainingRuns = vi.mocked(fetchTrainingRuns);
const mockedFetchProductionModel = vi.mocked(fetchProductionModel);

function makeProduction(overrides: Partial<ProductionModelInfo> = {}): ProductionModelInfo {
  return {
    training_run: null,
    model_type: "",
    prediction_target: "",
    prediction_target_label: "",
    r2_score: null,
    within_model_r2: null,
    mae: null,
    mae_display: null,
    deployed_at: null,
    is_serving: false,
    ...overrides,
  };
}
const mockedFetchTrainingRun = vi.mocked(fetchTrainingRun);
const mockedUploadTrainingDataset = vi.mocked(uploadTrainingDataset);
const mockedDeployTrainingRun = vi.mocked(deployTrainingRun);

function makeRun(overrides: Partial<MLTrainingRun> = {}): MLTrainingRun {
  return {
    id: 1,
    status: "succeeded",
    dataset_filename: "synthetic_bootstrap.csv",
    row_count: 500,
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

const runs: MLTrainingRun[] = [
  makeRun({
    id: 3,
    dataset_filename: "msrp_proxy_dataset.csv",
    created_at: "2026-03-01T00:00:00Z",
    rf_r2: 0.892,
    gb_r2: 0.85,
    deployed: true,
    deployed_model_type: "random_forest",
    known_issue_note: "This run's msrp_proxy feature leaked target data; do not cite its R2.",
  }),
  makeRun({
    id: 2,
    dataset_filename: "bad_upload.csv",
    created_at: "2026-02-01T00:00:00Z",
    status: "failed",
    rf_r2: null,
    gb_r2: null,
    rf_mae: null,
    gb_mae: null,
    rf_mae_display: null,
    gb_mae_display: null,
    mae_unit: null,
    row_count: null,
    error_message: "Training crashed: out of memory.",
  }),
  makeRun({ id: 1, created_at: "2026-01-01T00:00:00Z" }),
];

describe("MlModelHistoryPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("shows a loading state, then the populated chart and table", async () => {
    mockedFetchTrainingRuns.mockResolvedValueOnce(runs);

    render(<MlModelHistoryPage />);

    expect(await screen.findByText("R² trend")).toBeInTheDocument();
  });

  it("renders one table row per run, including the failed run's error message", async () => {
    mockedFetchTrainingRuns.mockResolvedValueOnce(runs);

    render(<MlModelHistoryPage />);
    await screen.findByText("R² trend");

    expect(screen.getByText("msrp_proxy_dataset.csv")).toBeInTheDocument();
    expect(screen.getByText("bad_upload.csv")).toBeInTheDocument();
    expect(screen.getByText("synthetic_bootstrap.csv")).toBeInTheDocument();
    expect(screen.getByText("Training crashed: out of memory.")).toBeInTheDocument();

    // Redesign UI-6b: one list item per run (was one table row per run).
    expect(screen.getByRole("list", { name: "Training runs" }).children).toHaveLength(3);
  });

  it("shows the deployed badge only for the run that actually deployed", async () => {
    mockedFetchTrainingRuns.mockResolvedValueOnce(runs);

    render(<MlModelHistoryPage />);
    await screen.findByText("R² trend");

    expect(screen.getByText("Random Forest")).toBeInTheDocument();
    expect(screen.getAllByText("Not deployed")).toHaveLength(2);
  });

  // --- Run 1 fix batch 5: the deployed run the forecast refuses ------------------

  it("says why the run marked deployed is not used, from the server's note", async () => {
    const note =
      "Run 5 is marked deployed but is not used: it predicts raw prices, and the forecast now needs the resale-price model (log scale).";
    mockedFetchTrainingRuns.mockResolvedValueOnce([
      makeRun({ id: 5, deployed: true, deployed_model_type: "random_forest", serving_note: note }),
      makeRun({ id: 8, serving_note: null }),
    ]);

    render(<MlModelHistoryPage />);
    await screen.findByText("R² trend");

    expect(screen.getByText(note)).toBeInTheDocument();
    expect(screen.getByText("Forecast off")).toBeInTheDocument();
    expect(screen.getAllByText("Not used")).toHaveLength(1);
  });

  it("shows no such note when the deployed run is in use", async () => {
    mockedFetchTrainingRuns.mockResolvedValueOnce(runs);

    render(<MlModelHistoryPage />);
    await screen.findByText("R² trend");

    expect(screen.queryByText("Forecast off")).not.toBeInTheDocument();
    expect(screen.queryByText("Not used")).not.toBeInTheDocument();
  });

  it("shows the known-issue note only for the annotated run", async () => {
    mockedFetchTrainingRuns.mockResolvedValueOnce(runs);

    render(<MlModelHistoryPage />);
    await screen.findByText("R² trend");

    expect(
      screen.getByText("This run's msrp_proxy feature leaked target data; do not cite its R2."),
    ).toBeInTheDocument();
  });

  // --- Audit batch 6b: MAE is shown in the unit that run was measured in ------

  it("shows a retention-ratio run's MAE as points of the car's price, never as RM", async () => {
    mockedFetchTrainingRuns.mockResolvedValueOnce([
      makeRun({
        id: 8, rf_mae: 0.0998, rf_mae_display: "10.0 pts of price",
        gb_mae: 0.0952, gb_mae_display: "9.5 pts of price", mae_unit: "points_of_price",
      }),
    ]);

    render(<MlModelHistoryPage />);
    await screen.findByText("R² trend");

    const row = screen.getByText("synthetic_bootstrap.csv").closest("li")!;
    expect(within(row).getByText("10.0 pts of price")).toBeInTheDocument();
    expect(within(row).getByText("9.5 pts of price")).toBeInTheDocument();
    expect(within(row).queryByText(/RM/)).not.toBeInTheDocument();
  });

  it("keeps RM for an older raw-price run, so a mixed history stays honest", async () => {
    mockedFetchTrainingRuns.mockResolvedValueOnce([
      makeRun({
        id: 8, created_at: "2026-10-05T00:00:00Z", dataset_filename: "new_ratio_run.csv",
        rf_mae: 0.0998, rf_mae_display: "10.0 pts of price",
        gb_mae: 0.0952, gb_mae_display: "9.5 pts of price", mae_unit: "points_of_price",
      }),
      makeRun({
        id: 5, created_at: "2026-09-04T00:00:00Z", dataset_filename: "old_raw_run.csv",
        rf_mae: 15881.93, rf_mae_display: "RM 15,881.93",
        gb_mae: 15598.68, gb_mae_display: "RM 15,598.68", mae_unit: "rm",
      }),
    ]);

    render(<MlModelHistoryPage />);
    await screen.findByText("R² trend");

    const newRow = screen.getByText("new_ratio_run.csv").closest("li")!;
    const oldRow = screen.getByText("old_raw_run.csv").closest("li")!;
    expect(within(newRow).getByText("10.0 pts of price")).toBeInTheDocument();
    expect(within(oldRow).getByText("RM 15,881.93")).toBeInTheDocument();
    expect(within(oldRow).getByText("RM 15,598.68")).toBeInTheDocument();
    expect(within(oldRow).queryByText(/pts of price/)).not.toBeInTheDocument();
  });

  it("shows a dash for a run with no MAE, and explains what MAE means under the table", async () => {
    mockedFetchTrainingRuns.mockResolvedValueOnce(runs);

    render(<MlModelHistoryPage />);
    await screen.findByText("R² trend");

    const failedRow = screen.getByText("bad_upload.csv").closest("li")!;
    expect(within(failedRow).getAllByText("-").length).toBeGreaterThanOrEqual(2);
    // ML batch 1: the unit follows each run's own target.
    expect(
      screen.getByText(/MAE is the average error in resale value, in the unit of each run's target: a resale-price \(log scale\) run shows its typical error as a share of the price; a value-retention-ratio run shows points of the car's price \(10 pts = 10% of the price\)/),
    ).toBeInTheDocument();
  });

  // --- ML batch 1: target, the second R², retired runs, the production card ---

  it("shows each run's target, both R² values and the log-price MAE wording", async () => {
    mockedFetchTrainingRuns.mockResolvedValueOnce([
      makeRun({
        id: 9, dataset_filename: "real_historical_pricing.csv",
        prediction_target: "log_resale_price", prediction_target_label: "Resale price (log scale)",
        rf_r2: 0.8673, rf_within_model_r2: 0.5487, rf_mae: 0.1966, rf_mae_display: "typical error ≈ 22% of price",
        gb_r2: 0.8789, gb_within_model_r2: 0.6489, gb_mae: 0.2022, gb_mae_display: "typical error ≈ 22% of price",
        mae_unit: "log_price", deploy_eligible: true, candidate_model_type: "gradient_boosting",
      }),
    ]);

    render(<MlModelHistoryPage />);
    await screen.findByText("R² trend");

    const row = screen.getByText("real_historical_pricing.csv").closest("li")!;
    expect(within(row).getByText("Resale price (log scale)")).toBeInTheDocument();
    for (const value of ["0.8673", "0.5487", "0.8789", "0.6489"]) {
      expect(within(row).getByText(value)).toBeInTheDocument();
    }
    expect(within(row).getAllByText("typical error ≈ 22% of price")).toHaveLength(2);
    // Redesign UI-6b: the run's own table of candidates (was the page table's "GB shape R²" column).
    expect(within(row).getByRole("rowheader", { name: "Gradient boosting" })).toBeInTheDocument();
    expect(within(row).getByRole("columnheader", { name: "Shape R²" })).toBeInTheDocument();
    expect(
      screen.getByText(
        /How well the model explains price differences between listings of the same car model, the part the depreciation curve uses\./,
      ),
    ).toBeInTheDocument();
    expect(screen.getByText(/Depreciation-shape R² \(within the same model\):/)).toBeInTheDocument();
  });

  it("marks a retired run, shows its reason and never offers to deploy it", async () => {
    const reason = "Retired: it predicts raw prices from msrp_proxy; replaced by the resale-price model (ML batch 1).";
    mockedFetchTrainingRuns.mockResolvedValueOnce([
      makeRun({ id: 5, retired_at: "2026-10-15T00:00:00Z", retired_reason: reason, deploy_eligible: true }),
      makeRun({ id: 6 }),
    ]);

    render(<MlModelHistoryPage />);
    await screen.findByText("R² trend");

    expect(screen.getByText("Retired")).toBeInTheDocument();
    expect(screen.getByText(reason)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Deploy New Model Weights" })).not.toBeInTheDocument();
    expect(screen.getAllByText("Not deployed")).toHaveLength(1); // only run 6
  });

  it("shows the production model's target and both R² values", async () => {
    mockedFetchTrainingRuns.mockResolvedValueOnce(runs);
    mockedFetchProductionModel.mockResolvedValueOnce(
      makeProduction({
        training_run: 9, model_type: "gradient_boosting", prediction_target: "log_resale_price",
        prediction_target_label: "Resale price (log scale)", r2_score: 0.8789, within_model_r2: 0.6489,
        mae: 0.2022, mae_display: "typical error ≈ 22% of price", deployed_at: "2026-10-16T00:00:00Z",
        is_serving: true,
      }),
    );

    render(<MlModelHistoryPage />);

    const heading = await screen.findByRole("heading", { name: "Production model" });
    const card = heading.closest("div")!;
    expect(within(card).getByText(/Gradient Boosting from run 9/)).toBeInTheDocument();
    expect(within(card).getByText("Resale price (log scale)")).toBeInTheDocument();
    expect(within(card).getByText("0.8789")).toBeInTheDocument();
    expect(within(card).getByText("0.6489")).toBeInTheDocument();
    expect(within(card).getByText("Depreciation-shape R² (within the same model)")).toBeInTheDocument();
    expect(within(card).queryByText(/Not used by the forecast/)).not.toBeInTheDocument();
  });

  // --- ML batch 2: the third candidate and the curve check ------------------------

  it("shows the log-linear candidate's R², shape R² and MAE, and a passed curve check", async () => {
    mockedFetchTrainingRuns.mockResolvedValueOnce([
      makeRun({
        id: 10, dataset_filename: "run10.csv",
        prediction_target: "log_resale_price", prediction_target_label: "Resale price (log scale)",
        ll_r2: 0.9124, ll_within_model_r2: 0.7199, ll_mae: 0.1473, ll_mae_display: "typical error ≈ 16% of price",
        ll_best_params: { alpha: 0.3857 }, curve_check_passed: true, curve_check_report: [],
        deploy_eligible: true, candidate_model_type: "log_linear",
      }),
    ]);

    render(<MlModelHistoryPage />);
    await screen.findByText("R² trend");

    const row = screen.getByText("run10.csv").closest("li")!;
    for (const value of ["0.9124", "0.7199", "typical error ≈ 16% of price", "Passed"]) {
      expect(within(row).getByText(value)).toBeInTheDocument();
    }
    // Redesign UI-6b: in the run's own details (were the page table's columns).
    expect(within(row).getByRole("rowheader", { name: "Log-linear" })).toBeInTheDocument();
    expect(within(row).getByText("Curve check")).toBeInTheDocument();
    // FX-3 (X13): the candidates in words (was "LL = Log-linear (hedonic)").
    expect(screen.getByText(/random forest, gradient boosting and log-linear\s+\(hedonic\)/)).toBeInTheDocument();
  });

  it("lists a failed curve check's problems, and says Not run for an older run", async () => {
    const problems = [
      "BMW 3 Series 320i Sport: keeps 95.3% after 12 months (limit 95%)",
      "Porsche 911 Carrera: value rises from year 0 to 1",
    ];
    mockedFetchTrainingRuns.mockResolvedValueOnce([
      makeRun({ id: 11, dataset_filename: "failed.csv", curve_check_passed: false, curve_check_report: problems,
        rejection_reason: "Curve check failed: BMW 3 Series 320i Sport: keeps 95.3% after 12 months (limit 95%) (+1 more)" }),
      makeRun({ id: 8, dataset_filename: "older.csv" }), // no curve_check_passed at all
    ]);

    render(<MlModelHistoryPage />);
    await screen.findByText("R² trend");

    const failed = screen.getByText("failed.csv").closest("li")!;
    expect(within(failed).getByText("Failed")).toBeInTheDocument();
    for (const problem of problems) expect(within(failed).getByText(problem)).toBeInTheDocument();
    expect(within(failed).getByText(/^Curve check failed:/)).toBeInTheDocument();
    const older = screen.getByText("older.csv").closest("li")!;
    expect(within(older).getByText("Not run")).toBeInTheDocument();
  });

  it("names a deployed log-linear model on the production card", async () => {
    mockedFetchTrainingRuns.mockResolvedValueOnce(runs);
    mockedFetchProductionModel.mockResolvedValueOnce(
      makeProduction({
        training_run: 10, model_type: "log_linear", model_type_label: "Log-linear (hedonic)",
        prediction_target: "log_resale_price", prediction_target_label: "Resale price (log scale)",
        r2_score: 0.9124, within_model_r2: 0.7199, is_serving: true,
      }),
    );

    render(<MlModelHistoryPage />);

    expect(await screen.findByText(/Log-linear \(hedonic\) from run 10/)).toBeInTheDocument();
  });

  it("says plainly when no model is deployed", async () => {
    mockedFetchTrainingRuns.mockResolvedValueOnce(runs);
    mockedFetchProductionModel.mockResolvedValueOnce(makeProduction());

    render(<MlModelHistoryPage />);

    expect(
      await screen.findByText(
        "No model is deployed. Buyers see the estimated depreciation curve from planning assumptions.",
      ),
    ).toBeInTheDocument();
  });

  it("shows an empty state when there are no training runs yet", async () => {
    mockedFetchTrainingRuns.mockResolvedValueOnce([]);

    render(<MlModelHistoryPage />);

    expect(await screen.findByText("No training runs yet")).toBeInTheDocument();
  });

  it("shows a generic error message when the request fails", async () => {
    mockedFetchTrainingRuns.mockRejectedValueOnce(new Error("network down"));

    render(<MlModelHistoryPage />);

    expect(
      await screen.findByText("Could not load training run history. Please try again."),
    ).toBeInTheDocument();
  });

  // --- Batch 6B: upload form -------------------------------------------

  it("shows the server's exact malformed-CSV message on a 400 upload", async () => {
    mockedFetchTrainingRuns.mockResolvedValueOnce([]);
    mockedUploadTrainingDataset.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 400,
        data: { detail: "Dataset upload failed. Missing required columns: [brand_code]." },
      },
    });
    const user = userEvent.setup();

    render(<MlModelHistoryPage />);
    await screen.findByText("No training runs yet");

    const file = new File(["vehicle_age,mileage\n1,2\n"], "dataset.csv", { type: "text/csv" });
    await user.upload(screen.getByLabelText("Training dataset file"), file);
    await user.click(screen.getByRole("button", { name: "Upload & Train" }));

    expect(
      await screen.findByText("Dataset upload failed. Missing required columns: [brand_code]."),
    ).toBeInTheDocument();
  });

  it("refetches the training run list after a successful upload", async () => {
    mockedFetchTrainingRuns.mockResolvedValueOnce([]).mockResolvedValueOnce(runs);
    mockedUploadTrainingDataset.mockResolvedValueOnce(makeRun({ id: 4, status: "succeeded" }));
    const user = userEvent.setup();

    render(<MlModelHistoryPage />);
    await screen.findByText("No training runs yet");

    const file = new File(["data"], "dataset.csv", { type: "text/csv" });
    await user.upload(screen.getByLabelText("Training dataset file"), file);
    await user.click(screen.getByRole("button", { name: "Upload & Train" }));

    await screen.findByText("R² trend");
    expect(mockedFetchTrainingRuns).toHaveBeenCalledTimes(2);
  });

  it("polls a still-running upload until it settles, then refetches", async () => {
    mockedFetchTrainingRuns.mockResolvedValueOnce([]).mockResolvedValueOnce(runs);
    mockedUploadTrainingDataset.mockResolvedValueOnce(makeRun({ id: 5, status: "running" }));
    mockedFetchTrainingRun.mockResolvedValueOnce(makeRun({ id: 5, status: "succeeded" }));
    const user = userEvent.setup();

    render(<MlModelHistoryPage />);
    await screen.findByText("No training runs yet");

    const file = new File(["data"], "dataset.csv", { type: "text/csv" });
    await user.upload(screen.getByLabelText("Training dataset file"), file);
    await user.click(screen.getByRole("button", { name: "Upload & Train" }));

    expect(await screen.findByText("Training in progress…")).toBeInTheDocument();
    // Real-timer wait: the page polls every POLL_INTERVAL_MS (3s) while a
    // run is still pending/running.
    await waitFor(() => expect(mockedFetchTrainingRun).toHaveBeenCalledWith(5), { timeout: 5000 });
  });

  // --- Batch 6B: manual deploy ------------------------------------------

  it("shows 'Ready to deploy' with a deploy button only for an eligible, not-yet-deployed run", async () => {
    mockedFetchTrainingRuns.mockResolvedValueOnce([
      makeRun({ id: 10, deploy_eligible: true, deployed: false, candidate_model_type: "gradient_boosting" }),
      makeRun({ id: 11, status: "failed", error_message: "boom" }),
      makeRun({ id: 12, deployed: true, deployed_model_type: "random_forest" }),
    ]);

    render(<MlModelHistoryPage />);
    await screen.findByText("R² trend");

    expect(screen.getByText("Ready to deploy")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Deploy New Model Weights" })).toBeInTheDocument();
    // Only one row is eligible - the failed and already-deployed rows get
    // neither the badge nor the button.
    expect(screen.getAllByRole("button", { name: "Deploy New Model Weights" })).toHaveLength(1);
  });

  it("opens the confirm dialog on Deploy and does not call the API until confirmed", async () => {
    mockedFetchTrainingRuns.mockResolvedValueOnce([
      makeRun({ id: 10, deploy_eligible: true, deployed: false, candidate_model_type: "gradient_boosting" }),
    ]);
    const user = userEvent.setup();

    render(<MlModelHistoryPage />);
    await screen.findByText("Ready to deploy");

    await user.click(screen.getByRole("button", { name: "Deploy New Model Weights" }));

    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    expect(mockedDeployTrainingRun).not.toHaveBeenCalled();
  });

  it("deploys the run and refetches the list once the dialog is confirmed", async () => {
    mockedFetchTrainingRuns
      .mockResolvedValueOnce([
        makeRun({ id: 10, deploy_eligible: true, deployed: false, candidate_model_type: "gradient_boosting" }),
      ])
      .mockResolvedValueOnce([makeRun({ id: 10, deployed: true, deployed_model_type: "gradient_boosting" })]);
    mockedDeployTrainingRun.mockResolvedValueOnce(
      makeRun({ id: 10, deployed: true, deployed_model_type: "gradient_boosting", deploy_eligible: false }),
    );
    const user = userEvent.setup();

    render(<MlModelHistoryPage />);
    await screen.findByText("Ready to deploy");

    await user.click(screen.getByRole("button", { name: "Deploy New Model Weights" }));
    const dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Deploy" }));

    expect(mockedDeployTrainingRun).toHaveBeenCalledWith(10);
    expect(await screen.findByText("Gradient Boosting")).toBeInTheDocument();
    expect(mockedFetchTrainingRuns).toHaveBeenCalledTimes(2);
  });

  // --- Redesign UI-6b: header, production figures, file picker, run list ----------

  it("has the page header, the production figures as stats and their explanation folded", async () => {
    mockedFetchTrainingRuns.mockResolvedValueOnce([makeRun()]);
    mockedFetchProductionModel.mockResolvedValueOnce(
      makeProduction({ training_run: 10, model_type: "log_linear", model_type_label: "Log-linear (hedonic)",
        r2_score: 0.9124, within_model_r2: 0.7199, mae_display: "typical error ≈ 16% of price" }),
    );
    render(<MlModelHistoryPage />);

    expect(screen.getByRole("heading", { level: 1, name: "ML model management" })).toBeInTheDocument();
    expect(screen.getByText("Train a candidate on a dataset, review it, then deploy it yourself.")).toBeInTheDocument();
    const card = (await screen.findByRole("heading", { name: "Production model" })).closest("div")!;
    const stat = (label: string) => within(card).getByText(label).nextElementSibling;
    expect(stat("R² (held-out)")).toHaveTextContent("0.9124");
    expect(stat("Depreciation-shape R² (within the same model)")).toHaveTextContent("0.7199");
    expect(stat("Typical error (MAE)")).toHaveTextContent("typical error ≈ 16% of price");
    expect(within(card).getByText("What do these numbers mean?").closest("details")).not.toBeNull();
  });

  it("picks the dataset through a button-styled file picker that names the chosen file", async () => {
    mockedFetchTrainingRuns.mockResolvedValueOnce([]);
    const user = userEvent.setup();
    render(<MlModelHistoryPage />);
    await screen.findByText("No training runs yet");

    expect(screen.getByText("No file chosen")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload & Train" })).toBeDisabled();
    await user.upload(screen.getByLabelText("Training dataset file"), new File(["a,b"], "march.csv", { type: "text/csv" }));
    expect(screen.getByText("march.csv")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload & Train" })).toBeEnabled();
    expect(screen.getByText(/A CSV with vehicle_age, mileage, resale_price/).closest("details")?.querySelector("summary")).toHaveTextContent(
      "What should the file contain?",
    );
  });

  it("lists a run as one line (date, dataset, target, the server's winner) that opens to every figure", async () => {
    mockedFetchTrainingRuns.mockResolvedValueOnce([
      makeRun({
        id: 10, dataset_filename: "run10.csv", row_count: 983,
        prediction_target: "log_resale_price", prediction_target_label: "Resale price (log scale)",
        rf_r2: 0.8603, gb_r2: 0.8776, ll_r2: 0.9124, ll_within_model_r2: 0.7199, ll_mae_display: "typical error ≈ 16% of price",
        curve_check_passed: true, curve_check_report: [], deployed: true, deployed_model_type: "log_linear",
        candidate_model_type: "log_linear",
      }),
    ]);
    const user = userEvent.setup();
    render(<MlModelHistoryPage />);
    await screen.findByText("R² trend");

    const item = screen.getByText("run10.csv").closest("li")!;
    const summary = item.querySelector("summary")!;
    expect(within(summary).getByText("983 rows")).toBeInTheDocument();
    expect(within(summary).getByText("Resale price (log scale)")).toBeInTheDocument();
    expect(within(summary).getByText("Best: Log-linear (hedonic), R² 0.9124")).toBeInTheDocument();
    expect(within(summary).getByText("Log-linear (hedonic)")).toHaveAttribute("data-tone", "positive");

    const details = item.querySelector("details")!;
    expect(details.open).toBe(false);
    await user.click(summary);
    expect(details.open).toBe(true);
    const llRow = within(item).getByRole("rowheader", { name: "Log-linear" }).closest("tr")!;
    expect(within(llRow).getAllByRole("cell").map((c) => c.textContent)).toEqual([
      "0.9124", "0.7199", "typical error ≈ 16% of price",
    ]);
  });

  it("keeps an eligible run's Deploy button outside its disclosure, with the same confirm", async () => {
    mockedFetchTrainingRuns.mockResolvedValueOnce([makeRun({ id: 11, deploy_eligible: true, candidate_model_type: "random_forest" })]);
    const user = userEvent.setup();
    render(<MlModelHistoryPage />);
    await screen.findByText("Ready to deploy");

    const button = screen.getByRole("button", { name: "Deploy New Model Weights" });
    expect(button.closest("details")).toBeNull();
    await user.click(button);
    expect(await screen.findByRole("alertdialog")).toHaveTextContent("Deploy this model to production?");
    expect(mockedDeployTrainingRun).not.toHaveBeenCalled();
  });
});
