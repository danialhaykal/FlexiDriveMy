import type { PaginatedResponse } from "./catalog";

// Mirrors apps/ml/serializers.py::MLTrainingRunSerializer exactly. Nullable
// rf_*/gb_* fields are real: a run whose status isn't "succeeded" (still
// running, or genuinely failed) has null R2/MAE/best_params for one or
// both estimators - never treat that as 0.

export type TrainingRunStatus = "pending" | "running" | "succeeded" | "failed";

// blank=True on the model field: "" means nothing has deployed from this
// run.
export type DeployedModelType = "random_forest" | "gradient_boosting" | "log_linear" | "";

// ML batch 1: what a run's estimators predict ("" = unknown / no metrics).
export type PredictionTarget = "log_resale_price" | "value_retention_ratio" | "raw_resale_price" | "";

export interface MLTrainingRun {
  id: number;
  status: TrainingRunStatus;
  dataset_filename: string;
  row_count: number | null;
  // Optional for an older response.
  prediction_target?: PredictionTarget;
  prediction_target_label?: string;
  rf_r2: number | null;
  // Depreciation-shape R² (within the same car model); null when not measured.
  rf_within_model_r2?: number | null;
  rf_mae: number | null;
  // MAE ready to show, built server-side in the unit that run was measured in:
  // "typical error ≈ 22% of price" for a log-price run, "10.0 pts of price"
  // for a retention-ratio run, "RM 15,881.93" for an older raw-price run, null
  // when the run recorded none. Never reformat rf_mae/gb_mae yourself - their
  // unit differs by run.
  rf_mae_display: string | null;
  rf_best_params: Record<string, unknown> | null;
  gb_r2: number | null;
  gb_within_model_r2?: number | null;
  gb_mae: number | null;
  gb_mae_display: string | null;
  gb_best_params: Record<string, unknown> | null;
  // ML batch 2: the third candidate, log-linear (hedonic). Optional for an
  // older response; null on runs from before it existed.
  ll_r2?: number | null;
  ll_within_model_r2?: number | null;
  ll_mae?: number | null;
  ll_mae_display?: string | null;
  ll_best_params?: Record<string, unknown> | null;
  // The winner's curve check: true passed, false failed (problems in
  // curve_check_report), null not run (older runs).
  curve_check_passed?: boolean | null;
  curve_check_report?: string[];
  // "log_price" | "points_of_price" (ratio target) | "rm" (raw resale price) |
  // null (no MAE).
  mae_unit: "log_price" | "points_of_price" | "rm" | null;
  // A retired run stays in the history but can never be deployed.
  retired_at?: string | null;
  retired_reason?: string;
  deployed: boolean;
  deployed_model_type: DeployedModelType;
  // Batch 6B - set when this run cleared BOTH deployment gates (see
  // apps.ml.training.pick_best_and_decide_deployment) but hasn't been
  // deployed yet; the human-gated "Deploy New Model Weights" action
  // (UC012 steps 7-8) is what actually hot-swaps production. False once
  // deployed (or if the run never cleared the gates at all).
  deploy_eligible: boolean;
  candidate_model_type: DeployedModelType;
  rejection_reason: string;
  error_message: string;
  // Manually-set annotation for a documented, human-confirmed incident on
  // this specific run (Sprint 13 addendum) - never auto-detected. Blank
  // ("") for every run except one a human has actually confirmed and
  // annotated via a data migration.
  known_issue_note: string;
  // Run 1 fix batch 5: set only on the run recorded as the production model
  // when the forecast refuses it ("Run 5 is marked deployed but is not used:
  // ..."); null otherwise. Optional for an older response.
  serving_note?: string | null;
  created_at: string;
  updated_at: string;
}

export type TrainingRunListResponse = PaginatedResponse<MLTrainingRun>;

// GET /api/ml/production-model/ (apps/ml/serializers.py::ProductionModelSerializer):
// the model buyers are served. Every field is null/"" when nothing is deployed.
export interface ProductionModelInfo {
  training_run: number | null;
  model_type: DeployedModelType;
  // "Log-linear (hedonic)" etc.; "" when nothing is deployed. Optional for an
  // older response.
  model_type_label?: string;
  prediction_target: PredictionTarget;
  prediction_target_label: string;
  r2_score: number | null;
  within_model_r2: number | null;
  mae: number | null;
  mae_display: string | null;
  deployed_at: string | null;
  // True only when buyers actually get this model's forecast.
  is_serving: boolean;
}
