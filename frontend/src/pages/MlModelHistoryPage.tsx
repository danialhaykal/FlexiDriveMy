import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import axios from "axios";
import { ChevronDown, Upload } from "lucide-react";
import {
  deployTrainingRun,
  fetchProductionModel,
  fetchTrainingRun,
  fetchTrainingRuns,
  uploadTrainingDataset,
} from "../api/ml";
import { listTotal } from "../api/allPages";
import { parseApiErrorMessage } from "../lib/apiErrors";
import { formatAdminDateTime } from "../lib/formatAdminDate";
import { predictionTargetLabel } from "../lib/mlLabels";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import type { MLTrainingRun, ProductionModelInfo } from "../types/ml";
import { TrainingRunTrendChart } from "../components/ml/TrainingRunTrendChart";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { EmptyState } from "../components/ui/EmptyState";
import { InfoExpander } from "../components/ui/InfoExpander";
import { ListCapNotice } from "../components/ui/ListCapNotice";
import { LoadingSkeleton } from "../components/ui/LoadingSkeleton";
import { PageHeader } from "../components/ui/PageHeader";
import { StatFigure } from "../components/ui/StatFigure";
import { Table } from "../components/ui/Table";
import { cn } from "../components/ui/cn";

// F012 / Sprint 13 - admin-only ML Model Training History. No backend
// changes: every figure here already exists in MLTrainingRun rows from
// real past retrains. This is the first admin-facing page in this
// codebase (F010/F011/F013's admin CRUD screens don't exist yet) - it's
// gated the same way the API itself already is (IsAdminRole server-side,
// ProtectedRoute requireRole="admin" here), nothing new invented for it.
//
// Batch 6B / UC012 steps 2-4 and 7-8, added in place (same route, same
// page - UC012 calls this whole thing "ML Model Management"): an upload
// form that triggers training, and a manual "Deploy New Model Weights"
// action separate from training itself - run_training_task only marks a
// run `deploy_eligible` when it clears both deployment gates; nothing
// hot-swaps ProductionModel until an admin explicitly deploys a specific
// eligible run here.
//
// Redesign UI-6b: the production model first, then "Train a new candidate",
// the R² trend and a compact list of runs - each opens to every figure the old
// 15-column table showed (nothing removed from view, only moved into the row).

const GENERIC_ERROR = "Could not load training run history. Please try again.";
const POLL_INTERVAL_MS = 3000;
const IN_PROGRESS_STATUSES: MLTrainingRun["status"][] = ["pending", "running"];


function formatR2(value: number | null): string {
  return value === null ? "-" : value.toFixed(4);
}

const MODEL_TYPE_LABELS: Record<string, string> = {
  random_forest: "Random Forest",
  gradient_boosting: "Gradient Boosting",
  log_linear: "Log-linear (hedonic)",
};

function modelTypeLabel(modelType: string): string {
  return MODEL_TYPE_LABELS[modelType] ?? modelType;
}

// ML batch 2: the winning candidate's curve check, a deploy rule next to the
// R² gate. Older runs predate it ("Not run").
function CurveCheckResult({ run }: { run: MLTrainingRun }) {
  if (run.curve_check_passed === true) return <Badge tone="positive">Passed</Badge>;
  if (run.curve_check_passed === false) {
    return (
      <div className="flex flex-col items-start gap-1">
        <Badge tone="danger">Failed</Badge>
        <ul className="max-w-xs list-disc pl-4 text-caption text-ink-muted">
          {(run.curve_check_report ?? []).map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      </div>
    );
  }
  return <span className="text-caption text-ink-muted">Not run</span>;
}

export const SHAPE_R2_LABEL = "Depreciation-shape R² (within the same model)";
export const SHAPE_R2_HELP =
  "How well the model explains price differences between listings of the same car model, the part the depreciation curve uses.";

// ML batch 1: which model buyers are actually served, with its target and both
// R² values. Hidden if the request fails - the run history still works.
// Redesign UI-6b: the figures as StatFigures (the API's values, unchanged), the
// explanation folded in "What do these numbers mean?".
function ProductionModelCard({ production }: { production: ProductionModelInfo }) {
  const hasModel = production.training_run !== null && production.model_type !== "";
  return (
    <Card>
      <h2 className="text-h3 font-semibold text-ink">Production model</h2>
      {!hasModel && (
        <p className="mt-1 text-small text-ink-muted">
          No model is deployed. Buyers see the estimated depreciation curve from planning assumptions.
        </p>
      )}
      {hasModel && (
        <>
          <p className="mt-1 text-small text-ink-muted">
            {production.model_type_label || modelTypeLabel(production.model_type)} from run{" "}
            {production.training_run}
            {production.deployed_at ? `, deployed ${formatAdminDateTime(production.deployed_at)}` : ""}.
            {!production.is_serving && " Not used by the forecast: its target is not the one the forecast needs."}
          </p>
          <div className="mt-5 grid gap-x-6 gap-y-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatFigure
              label="Target"
              value={predictionTargetLabel(production.prediction_target, production.prediction_target_label) || "Unknown"}
            />
            <StatFigure label="R² (held-out)" value={formatR2(production.r2_score)} size="money-sm" />
            <StatFigure label={SHAPE_R2_LABEL} value={formatR2(production.within_model_r2)} size="money-sm" />
            <StatFigure label="Typical error (MAE)" value={production.mae_display ?? "-"} />
          </div>
          <InfoExpander summary="What do these numbers mean?" className="mt-4">
            <p>
              R² (held-out) is how much of the variation in resale prices the model explains on listings it
              never saw in training; it is the figure the 0.80 deployment check uses.
            </p>
            <p className="mt-1">
              {SHAPE_R2_LABEL}: {SHAPE_R2_HELP}
            </p>
            <p className="mt-1">The typical error is the average error in resale value, in this model's own unit.</p>
          </InfoExpander>
        </>
      )}
    </Card>
  );
}

// The candidates' figures, as the API recorded them - one row per candidate.
// FX-3 (X13): each named in words (it was "RF" / "GB" / "LL").
const CANDIDATES: { key: "rf" | "gb" | "ll"; name: string }[] = [
  { key: "rf", name: "Random forest" },
  { key: "gb", name: "Gradient boosting" },
  { key: "ll", name: "Log-linear" },
];

function candidateFigures(run: MLTrainingRun, key: "rf" | "gb" | "ll") {
  if (key === "rf") return { r2: run.rf_r2, shape: run.rf_within_model_r2 ?? null, mae: run.rf_mae_display };
  if (key === "gb") return { r2: run.gb_r2, shape: run.gb_within_model_r2 ?? null, mae: run.gb_mae_display };
  return { r2: run.ll_r2 ?? null, shape: run.ll_within_model_r2 ?? null, mae: run.ll_mae_display ?? null };
}

// The winner the server picked (candidate_model_type) and its R², as recorded.
function bestCandidateText(run: MLTrainingRun): string | null {
  const candidate = CANDIDATES.find((c) => MODEL_TYPE_KEYS[c.key] === run.candidate_model_type);
  if (!candidate) return null;
  return `Best: ${modelTypeLabel(run.candidate_model_type)}, R² ${formatR2(candidateFigures(run, candidate.key).r2)}`;
}

const MODEL_TYPE_KEYS: Record<"rf" | "gb" | "ll", string> = {
  rf: "random_forest",
  gb: "gradient_boosting",
  ll: "log_linear",
};

// The deployment status badges - the same states the old table showed.
// FX-3 (X13): "Live" marks the run buyers are served right now (the
// production model's own run, while it is serving).
function RunStatusBadges({ run, isLive }: { run: MLTrainingRun; isLive: boolean }) {
  return (
    <span className="flex flex-wrap items-center gap-1.5">
      {isLive && <Badge tone="recommended">Live</Badge>}
      {run.deployed && <Badge tone="positive">{modelTypeLabel(run.deployed_model_type)}</Badge>}
      {run.serving_note && <Badge tone="warning">Not used</Badge>}
      {run.retired_at && <Badge tone="neutral">Retired</Badge>}
      {!run.retired_at && !run.deployed && run.deploy_eligible && <Badge tone="warning">Ready to deploy</Badge>}
      {!run.retired_at && !run.deployed && !run.deploy_eligible && <Badge tone="neutral">Not deployed</Badge>}
      {run.status === "failed" && <Badge tone="danger">Training failed</Badge>}
      {IN_PROGRESS_STATUSES.includes(run.status) && <Badge tone="neutral">In progress</Badge>}
      {run.known_issue_note && <Badge tone="warning">Known issue</Badge>}
    </span>
  );
}

// One training run: a summary line that opens to every figure the old table
// showed (each candidate's R², shape R² and MAE, the curve check and the
// deployment notes). An eligible run's Deploy button sits under it, outside
// the disclosure, with the same confirm.
interface TrainingRunItemProps {
  run: MLTrainingRun;
  isLive: boolean;
  onDeploy: (id: number) => void;
}

function TrainingRunItem({ run, isLive, onDeploy }: TrainingRunItemProps) {
  const best = bestCandidateText(run);
  return (
    <li className="border-b border-border last:border-b-0">
      <details className="group">
        <summary
          className={cn(
            "flex cursor-pointer list-none flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 hover:bg-surface-subtle sm:px-6",
            "[&::-webkit-details-marker]:hidden focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary-500",
          )}
        >
          <span className="flex w-40 shrink-0 flex-col">
            <span className="text-small font-semibold text-ink">Run {run.id}</span>
            <span className="text-caption tabular-nums text-ink-muted">{formatAdminDateTime(run.created_at)}</span>
          </span>
          <span className="flex min-w-0 flex-1 basis-48 flex-col">
            <span className="truncate text-small font-medium text-ink">{run.dataset_filename || "-"}</span>
            <span className="text-caption text-ink-muted">
              <span>{run.row_count === null ? "-" : `${run.row_count.toLocaleString("en-MY")} rows`}</span>
              {" · "}
              <span>{predictionTargetLabel(run.prediction_target, run.prediction_target_label) || "-"}</span>
            </span>
          </span>
          <span className="text-small tabular-nums text-ink">
            {best ?? <span className="text-ink-muted">No winner recorded</span>}
          </span>
          <RunStatusBadges run={run} isLive={isLive} />
          <ChevronDown
            className="ml-auto h-4 w-4 shrink-0 text-ink-muted transition-transform group-open:rotate-180"
            aria-hidden="true"
          />
        </summary>
        <div className="grid gap-6 border-t border-border bg-page-bg px-4 py-4 sm:px-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
          <div className="min-w-0 overflow-hidden rounded-control border border-border bg-surface">
            <Table>
              <Table.Head>
                <Table.Row>
                  <Table.HeaderCell>Candidate</Table.HeaderCell>
                  <Table.HeaderCell numeric>R²</Table.HeaderCell>
                  <Table.HeaderCell numeric>Shape R²</Table.HeaderCell>
                  <Table.HeaderCell numeric>MAE</Table.HeaderCell>
                </Table.Row>
              </Table.Head>
              <Table.Body>
                {CANDIDATES.map((candidate) => {
                  const figures = candidateFigures(run, candidate.key);
                  return (
                    <Table.Row key={candidate.key}>
                      <Table.HeaderCell scope="row" className="font-medium text-ink">
                        {candidate.name}
                      </Table.HeaderCell>
                      <Table.Cell numeric>{formatR2(figures.r2)}</Table.Cell>
                      <Table.Cell numeric>{formatR2(figures.shape)}</Table.Cell>
                      <Table.Cell numeric>{figures.mae ?? "-"}</Table.Cell>
                    </Table.Row>
                  );
                })}
              </Table.Body>
            </Table>
          </div>
          <dl className="flex min-w-0 flex-col gap-3 text-small">
            <div>
              <dt className="text-caption font-semibold text-ink-muted">Curve check</dt>
              <dd className="mt-1">
                <CurveCheckResult run={run} />
              </dd>
            </div>
            <div>
              <dt className="text-caption font-semibold text-ink-muted">Deployment</dt>
              {/* The status badges are on the summary line; the notes behind them are here. */}
              <dd className="mt-1 flex flex-col items-start gap-1">
                {run.deployed && <p className="text-caption text-ink-muted">Deployed: {modelTypeLabel(run.deployed_model_type)} model.</p>}
                {run.retired_at && run.retired_reason && (
                  <p className="text-caption text-ink-muted">{run.retired_reason}</p>
                )}
                {run.status === "failed" && <p className="text-caption text-danger-700">{run.error_message}</p>}
                {run.status !== "failed" && run.status !== "succeeded" && (
                  <p className="text-caption text-ink-muted">Status: {run.status}</p>
                )}
                {run.status === "succeeded" && !run.deployed && !run.deploy_eligible && run.rejection_reason && (
                  <p className="text-caption text-ink-muted">{run.rejection_reason}</p>
                )}
                {run.known_issue_note && <p className="text-caption text-warning-700">{run.known_issue_note}</p>}
              </dd>
            </div>
          </dl>
        </div>
      </details>
      {!run.retired_at && !run.deployed && run.deploy_eligible && (
        <div className="flex flex-wrap items-center gap-3 px-4 pb-3 sm:px-6">
          <Button variant="secondary" onClick={() => onDeploy(run.id)}>
            Deploy New Model Weights
          </Button>
          <span className="text-caption text-ink-muted">Cleared both deployment checks.</span>
        </div>
      )}
    </li>
  );
}

export function MlModelHistoryPage() {
  useDocumentTitle("ML Model Management");
  const [runs, setRuns] = useState<MLTrainingRun[]>([]);
  // Run 3 fix batch 4 (F-17): the server's run count, for ListCapNotice.
  const [runsTotal, setRunsTotal] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [pollingRunId, setPollingRunId] = useState<number | null>(null);
  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const [deployTargetId, setDeployTargetId] = useState<number | null>(null);
  const [isDeploying, setIsDeploying] = useState(false);
  const [deployError, setDeployError] = useState<string | null>(null);
  const [production, setProduction] = useState<ProductionModelInfo | null>(null);

  function loadProduction() {
    return Promise.resolve()
      .then(() => fetchProductionModel())
      .then((data) => setProduction(data ?? null))
      .catch(() => setProduction(null));
  }

  function loadRuns() {
    setIsLoading(true);
    setError(null);
    return fetchTrainingRuns()
      .then((data) => {
        setRuns(data);
        setRunsTotal(listTotal(data));
      })
      .catch((err: unknown) => {
        if (axios.isAxiosError(err)) {
          const detail = (err.response?.data as { detail?: unknown } | undefined)?.detail;
          setError(typeof detail === "string" ? detail : GENERIC_ERROR);
        } else {
          setError(GENERIC_ERROR);
        }
      })
      .finally(() => {
        setIsLoading(false);
      });
  }

  useEffect(() => {
    void loadRuns();
    void loadProduction();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Polls a just-uploaded run while it's still pending/running - in this
  // dev environment CELERY_TASK_ALWAYS_EAGER=True means a run is already
  // succeeded/failed by the time the upload response comes back, so this
  // loop typically never fires more than once in practice, but a real
  // async deployment needs it. Basic setInterval + cleanup-on-unmount is
  // enough here - not over-building a generic polling hook for one use.
  useEffect(() => {
    if (pollingRunId === null) return;

    pollIntervalRef.current = setInterval(() => {
      fetchTrainingRun(pollingRunId)
        .then((run) => {
          if (IN_PROGRESS_STATUSES.includes(run.status)) return;
          setPollingRunId(null);
          void loadRuns();
        })
        .catch(() => {
          setPollingRunId(null);
        });
    }, POLL_INTERVAL_MS);

    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pollingRunId]);

  async function handleUploadSubmit(event: FormEvent) {
    event.preventDefault();
    if (!uploadFile) return;
    setIsUploading(true);
    setUploadError(null);
    try {
      const run = await uploadTrainingDataset(uploadFile);
      setUploadFile(null);
      await loadRuns();
      if (IN_PROGRESS_STATUSES.includes(run.status)) {
        setPollingRunId(run.id);
      }
    } catch (err: unknown) {
      setUploadError(
        (axios.isAxiosError(err) && parseApiErrorMessage(err.response?.data)) ||
          "Could not upload this dataset. Please try again.",
      );
    } finally {
      setIsUploading(false);
    }
  }

  async function handleConfirmDeploy() {
    if (deployTargetId === null) return;
    setIsDeploying(true);
    setDeployError(null);
    try {
      const updated = await deployTrainingRun(deployTargetId);
      setRuns((prev) => prev.map((run) => (run.id === updated.id ? updated : run)));
      setDeployTargetId(null);
      // Server is the source of truth for every OTHER row too (deploying
      // this run clears whichever other run previously read
      // deployed=true) - refetch the whole list rather than hand-patching
      // local state for rows this response doesn't itself describe.
      await Promise.all([loadRuns(), loadProduction()]);
    } catch (err: unknown) {
      setDeployError(
        (axios.isAxiosError(err) && parseApiErrorMessage(err.response?.data)) ||
          "Could not deploy this model. Please try again.",
      );
    } finally {
      setIsDeploying(false);
    }
  }

  return (
    <div className="mx-auto max-w-6xl px-4 pb-16 pt-8 sm:pt-10">
      <PageHeader
        title="ML model management"
        subtitle="Train a candidate on a dataset, review it, then deploy it yourself."
      />

      {/* Run 1 fix batch 5: why buyers see the estimated curve - the server's own
          admin note for a deployed run it refuses to use. */}
      {!isLoading &&
        !error &&
        runs
          .filter((run) => run.serving_note)
          .map((run) => (
            <div
              key={`serving-${run.id}`}
              role="status"
              className="mt-6 flex items-start gap-3 rounded-card border border-warning-200 bg-warning-50 p-3"
            >
              <Badge tone="warning">Forecast off</Badge>
              <p className="text-small text-warning-700">{run.serving_note}</p>
            </div>
          ))}

      <div className="mt-6 flex flex-col gap-6">
        {production && <ProductionModelCard production={production} />}

        <Card>
          <h2 className="text-h3 font-semibold text-ink">Train a new candidate</h2>
          <p className="mt-1 text-small text-ink-muted">
            Upload a training dataset; the run trains every candidate and marks the best one eligible only
            if it clears both deployment checks.
          </p>
          <form className="mt-4 flex flex-wrap items-center gap-3" onSubmit={handleUploadSubmit}>
            {/* A real file input, visually replaced by a button-styled label. */}
            <label
              className={cn(
                "inline-flex cursor-pointer items-center gap-2 rounded-control border border-border bg-surface px-4 py-2 text-small font-semibold text-ink transition-colors hover:bg-surface-subtle",
                "focus-within:outline-none focus-within:ring-2 focus-within:ring-primary-500 focus-within:ring-offset-2",
              )}
            >
              <Upload className="h-4 w-4" aria-hidden="true" />
              Choose CSV file
              <input
                type="file"
                accept=".csv"
                aria-label="Training dataset file"
                onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
                className="sr-only"
              />
            </label>
            <span className="min-w-0 max-w-full truncate text-small text-ink-muted" aria-live="polite">
              {uploadFile ? uploadFile.name : "No file chosen"}
            </span>
            <Button type="submit" isLoading={isUploading} disabled={!uploadFile}>
              Upload &amp; Train
            </Button>
          </form>
          <InfoExpander summary="What should the file contain?" className="mt-3">
            A CSV with vehicle_age, mileage, resale_price, brand_code, engine_litres, body_type and
            recond columns. An optional model_key column (the car model, e.g. "BMW 320i") lets the run
            measure its depreciation-shape R².
          </InfoExpander>
          {uploadError && <p className="mt-3 text-small text-danger-700">{uploadError}</p>}
          {pollingRunId !== null && (
            <p className="mt-3 text-small text-ink-muted">Training in progress&hellip;</p>
          )}
        </Card>

        {isLoading && <LoadingSkeleton className="h-80 w-full" />}

        {!isLoading && error && (
          <div role="alert">
            <EmptyState
              title="History unavailable"
              description={error}
              action={<Button onClick={() => void loadRuns()}>Try again</Button>}
            />
          </div>
        )}

        {!isLoading && !error && runs.length === 0 && (
          <EmptyState
            title="No training runs yet"
            description="Upload a dataset to trigger the first retrain."
          />
        )}

        {!isLoading && !error && runs.length > 0 && (
          <>
            <Card>
              <h2 className="text-h3 font-semibold text-ink">R² trend</h2>
              <p className="mt-1 text-small text-ink-muted">
                Random Forest, Gradient Boosting and log-linear validation R² across every recorded run, oldest
                to newest, one set of lines per prediction target (log-linear runs start later, when that
                candidate was added). The larger, filled dot marks the run that actually deployed.
              </p>
              <div className="mt-4">
                <TrainingRunTrendChart runs={runs} />
              </div>
            </Card>

            {deployError && <p className="text-small text-danger-700">{deployError}</p>}

            <Card padding="none">
              <div className="px-4 pt-5 sm:px-6">
                <h2 className="text-h3 font-semibold text-ink">Training runs</h2>
                <p className="mt-1 text-small text-ink-muted">
                  Newest first. Open a run to see every candidate's figures, the curve check and its deployment
                  notes.
                </p>
              </div>
              <ul aria-label="Training runs" className="mt-3 border-t border-border">
                {runs.map((run) => (
                  <TrainingRunItem
                    key={run.id}
                    run={run}
                    isLive={production?.is_serving === true && production.training_run === run.id}
                    onDeploy={setDeployTargetId}
                  />
                ))}
              </ul>
              <div className="px-4">
                <ListCapNotice shown={runs.length} total={runsTotal} />
              </div>
              <div className="border-t border-border px-4 py-3 sm:px-6">
                <InfoExpander summary="How to read these runs">
                  <div className="flex flex-col gap-2">
                    <p>
                      Each run trains three candidates: random forest, gradient boosting and log-linear
                      (hedonic). The candidate with the highest R² wins.
                    </p>
                    <p>
                      <span className="font-medium text-ink">{SHAPE_R2_LABEL}:</span> {SHAPE_R2_HELP} The R²
                      column is the one the 0.80 deployment check uses.
                    </p>
                    <p>
                      <span className="font-medium text-ink">Curve check:</span> before a run can be deployed,
                      the winner's depreciation curve for every catalog car it covers must fall from year to year,
                      keep at most 95% after 12 months and keep 20%-75% after 60 months. These are sanity limits,
                      not market claims.
                    </p>
                    <p>
                      MAE is the average error in resale value, in the unit of each run's target: a resale-price
                      (log scale) run shows its typical error as a share of the price; a value-retention-ratio
                      run shows points of the car's price (10 pts = 10% of the price); older runs trained on the
                      raw resale price show their error in RM.
                    </p>
                  </div>
                </InfoExpander>
              </div>
            </Card>
          </>
        )}
      </div>

      <ConfirmDialog
        isOpen={deployTargetId !== null}
        title="Deploy this model to production?"
        message="This immediately replaces the live production model used for every resale-value prediction. This cannot be undone from here - a replacement would need its own deploy."
        confirmLabel="Deploy"
        isConfirming={isDeploying}
        onConfirm={() => void handleConfirmDeploy()}
        onCancel={() => setDeployTargetId(null)}
      />
    </div>
  );
}
