import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ChartLine, ChevronLeft, Layers, Sparkles } from "lucide-react";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { deleteScenario, getScenario } from "../api/scenarios";
import type { Scenario } from "../types/scenarios";
import { formatCurrency } from "../lib/formatCurrency";
import { formatSavedDate } from "../lib/formatSavedDate";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { EmptyState } from "../components/ui/EmptyState";
import { InfoExpander } from "../components/ui/InfoExpander";
import { LoadingSkeleton } from "../components/ui/LoadingSkeleton";
import { PageHeader } from "../components/ui/PageHeader";
import { PathwaysTable } from "../components/comparisons/PathwaysTable";
import { TcoReportView } from "../components/depreciation/TcoReportView";
import { ScoringResultView } from "../components/scoring/ScoringResultView";

// F009 / UC009 step 7: reloads a saved scenario "from the stored
// payload" - deliberately NOT by re-calling /comparisons/,
// /depreciation/tco/, or /scoring/. Only GET /api/scenarios/:id/ is
// called here; every figure below renders straight from that response's
// payload, unchanged, so this stays as it was even if pricing config has
// since changed. Since run 1 fix batch 2 the server calculates that
// payload when the user saves; the banner says who calculated it.

const GENERIC_ERROR = "This saved comparison could not be found.";
const DELETE_ERROR = "Could not delete this comparison. Please try again.";

// The compare page's tab icons, beside the matching saved section's heading.
const SECTION_ICON_CLASS = "mr-2 inline h-5 w-5 align-[-3px] text-ink-muted";

export function SavedScenarioPage() {
  const { id } = useParams<{ id: string }>();
  const [scenario, setScenario] = useState<Scenario | null>(null);
  useDocumentTitle(scenario?.title ?? "Saved Comparison");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // FX-1 (X5): delete from the saved page itself, with the same dialog and wording as My Comparisons.
  const navigate = useNavigate();
  const [isConfirmOpen, setIsConfirmOpen] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  async function handleDelete() {
    if (!scenario) return;
    setIsDeleting(true);
    setDeleteError(null);
    try {
      await deleteScenario(scenario.id);
      // My Comparisons loads its list when it opens, so it no longer shows this one.
      navigate("/scenarios");
    } catch {
      setDeleteError(DELETE_ERROR);
      setIsConfirmOpen(false);
    } finally {
      setIsDeleting(false);
    }
  }

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setIsLoading(true);
    getScenario(id)
      .then((data) => {
        if (!cancelled) setScenario(data);
      })
      .catch(() => {
        if (!cancelled) setError(GENERIC_ERROR);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  if (isLoading) {
    return (
      <div className="mx-auto mt-10 max-w-5xl px-4">
        <LoadingSkeleton variant="text" className="w-48" />
        <LoadingSkeleton className="mt-4 h-40 w-full" />
      </div>
    );
  }

  if (error || !scenario) {
    return (
      <div className="mx-auto mt-10 max-w-5xl px-4">
        <EmptyState title="Comparison not found" description={error ?? undefined} />
      </div>
    );
  }

  const { payload } = scenario;
  const savedOn = formatSavedDate(scenario.updated_at);
  const isServerBuilt = payload.snapshotVersion === 2;

  return (
    <div className="mx-auto mt-10 max-w-5xl px-4 pb-16">
      <PageHeader
        breadcrumb={
          <Link
            to="/scenarios"
            className="inline-flex items-center gap-1 rounded-control font-medium text-ink-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
          >
            <ChevronLeft className="h-4 w-4" aria-hidden="true" />
            Back to My Comparisons
          </Link>
        }
        title={scenario.title}
        // "–" for a field an older snapshot does not have, never a guess.
        subtitle={`${scenario.vehicle_label} · ${payload.downpayment ? formatCurrency(payload.downpayment) : "–"} downpayment · ${payload.tenureMonths ?? "–"} months`}
        actions={
          <Button variant="danger-quiet" onClick={() => setIsConfirmOpen(true)} isLoading={isDeleting}>
            Delete
          </Button>
        }
      />
      {deleteError && (
        <p role="alert" className="mt-3 text-small text-danger-700">
          {deleteError}
        </p>
      )}
      <ConfirmDialog
        isOpen={isConfirmOpen}
        title="Delete this saved comparison?"
        message="This cannot be undone."
        confirmLabel="Delete"
        isConfirming={isDeleting}
        onConfirm={() => void handleDelete()}
        onCancel={() => setIsConfirmOpen(false)}
      />

      {/* Says who calculated the figures (run 1 fix batch 2): version-2
          snapshots are built by the server; older rows were built by the
          browser of an earlier version and are kept as they were. Redesign
          UI-4: a slim badge, with the full sentence folded beside it. */}
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
        <Badge tone="neutral">
          {isServerBuilt ? `Saved ${savedOn} · figures frozen` : `Saved ${savedOn} · earlier version`}
        </Badge>
        <InfoExpander summary="About these figures">
          {isServerBuilt
            ? `Saved on ${savedOn}. These figures were calculated by FlexiDriveMy when you saved and are kept unchanged, even if rates or prices change later.`
            : `Saved on ${savedOn} by an earlier version of FlexiDriveMy. Figures are kept unchanged from that time.`}
        </InfoExpander>
      </div>

      <div className="mt-6 flex flex-col gap-8">
        <section>
          <h2 className="text-h2 font-semibold text-ink">
            <Layers className={SECTION_ICON_CLASS} aria-hidden="true" />
            Financing Pathways
          </h2>
          <div className="mt-4">
            {/* The wording flag comes from the snapshot itself, never a fresh
                profile fetch - this page makes exactly one API call. */}
            <PathwaysTable
              comparison={payload.comparison}
              prefersIslamicFinancing={payload.prefersIslamicFinancing === true}
              // The saved recommendation (the scoring API's own result, as saved), if any.
              recommendedPathway={payload.scoring?.recommended_pathway ?? null}
            />
          </div>
        </section>

        {payload.tco && (
          <section>
            <h2 className="text-h2 font-semibold text-ink">
              <ChartLine className={SECTION_ICON_CLASS} aria-hidden="true" />
              TCO Breakdown &amp; Depreciation
            </h2>
            <div className="mt-4">
              <TcoReportView report={payload.tco} />
            </div>
          </section>
        )}

        {!payload.tco && payload.tcoUnavailableReason && (
          <section>
            <h2 className="text-h2 font-semibold text-ink">
              <ChartLine className={SECTION_ICON_CLASS} aria-hidden="true" />
              TCO Breakdown &amp; Depreciation
            </h2>
            <div className="mt-4">
              <EmptyState title="TCO unavailable when this was saved" description={payload.tcoUnavailableReason} />
            </div>
          </section>
        )}

        {payload.scoring && (
          <section>
            <h2 className="text-h2 font-semibold text-ink">
              <Sparkles className={SECTION_ICON_CLASS} aria-hidden="true" />
              AI Recommendation
            </h2>
            <div className="mt-4">
              <ScoringResultView result={payload.scoring} />
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
