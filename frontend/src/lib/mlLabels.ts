import type { PredictionTarget } from "../types/ml";

// FX-3 (X13): plain names for what a training run predicts, instead of the
// audit codes in the server's labels ("Value-retention ratio (C8)", "Raw
// resale price (legacy, pre-C8)"). The meaning is the code's own
// (apps/ml/models.py::PredictionTarget): the log of the resale price is the
// current target; the value-retention ratio came before it and the raw resale
// price before that. Display only; an unknown target keeps the server's label.
const PREDICTION_TARGET_LABELS: Record<Exclude<PredictionTarget, "">, string> = {
  log_resale_price: "Resale price (log scale)",
  value_retention_ratio: "Value-retention ratio (older runs)",
  raw_resale_price: "Raw resale price (oldest runs)",
};

export function predictionTargetLabel(target: PredictionTarget | undefined, serverLabel?: string): string {
  if (target && target in PREDICTION_TARGET_LABELS) return PREDICTION_TARGET_LABELS[target as Exclude<PredictionTarget, "">];
  return serverLabel ?? "";
}
