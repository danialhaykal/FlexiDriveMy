import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronLeft, FolderOpen } from "lucide-react";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useCatalogVehiclesById } from "../hooks/useCatalogVehiclesById";
import { useMileageBandOptions } from "../hooks/useMileageBandOptions";
import { deleteScenario, listScenarios } from "../api/scenarios";
import type { Scenario } from "../types/scenarios";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { ConfirmDialog } from "../components/ui/ConfirmDialog";
import { EmptyState } from "../components/ui/EmptyState";
import { LoadingSkeleton } from "../components/ui/LoadingSkeleton";
import { PageHeader } from "../components/ui/PageHeader";
import { cn } from "../components/ui/cn";
import { ScenarioPhoto, StoredMonthlies, scenarioMeta } from "../components/scenarios/ScenarioSummary";

// F009 / UC009 "My Comparisons" - lists the current user's saved
// scenarios (server-scoped; nothing extra needed client-side for that).
// Opening one navigates to /scenarios/:id (SavedScenarioPage), which
// renders straight from the stored payload rather than recalculating.
// Redesign UI-4: one card per scenario with the car's photo (from the
// catalog list) and the stored monthly figures exactly as saved.

const GENERIC_LOAD_ERROR = "Could not load your saved comparisons. Please try again.";
const GENERIC_DELETE_ERROR = "Could not delete this comparison. Please try again.";

const LINK_BUTTON_BASE = cn(
  "inline-flex items-center justify-center gap-2 rounded-control px-4 py-2 text-small font-semibold transition-colors",
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2",
);

export function ScenariosPage() {
  useDocumentTitle("My Comparisons");
  const bands = useMileageBandOptions();
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [deletingId, setDeletingId] = useState<number | null>(null);
  // FX-1 (X5): the comparison waiting for the delete confirmation (the app's own dialog, not window.confirm).
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  // QA audit L16: keyed by scenario id, separate from the page-level
  // load `error` above - a failed delete previously reused that SAME
  // state, and the page's render logic hides the entire list whenever
  // `error` is set, so one row's failed delete made every OTHER saved
  // scenario disappear from view too, not just show a problem for that
  // one row.
  const [deleteErrors, setDeleteErrors] = useState<Record<number, string>>({});
  const vehiclesById = useCatalogVehiclesById(scenarios.length > 0);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    listScenarios()
      .then((data) => {
        if (!cancelled) setScenarios(data);
      })
      .catch(() => {
        if (cancelled) return;
        setScenarios([]);
        setError(GENERIC_LOAD_ERROR);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  async function handleDelete(id: number) {
    setDeletingId(id);
    setDeleteErrors((current) => {
      const next = { ...current };
      delete next[id];
      return next;
    });
    try {
      await deleteScenario(id);
      setScenarios((current) => current.filter((scenario) => scenario.id !== id));
    } catch {
      setDeleteErrors((current) => ({ ...current, [id]: GENERIC_DELETE_ERROR }));
    } finally {
      setDeletingId(null);
      setConfirmDeleteId(null);
    }
  }

  return (
    <div className="mx-auto max-w-5xl px-4 pb-16 pt-8 sm:pt-10">
      <PageHeader
        breadcrumb={
          <Link
            to="/"
            className="inline-flex items-center gap-1 rounded-control font-medium text-ink-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
          >
            <ChevronLeft className="h-4 w-4" aria-hidden="true" />
            Back to dashboard
          </Link>
        }
        title="My comparisons"
        subtitle={!isLoading && !error ? `${scenarios.length} saved` : undefined}
      />
      <p className="mt-2 text-small text-ink-muted">
        Saved comparisons show the exact figures you saw at the time - reopening one never
        recalculates them.
      </p>

      <div className="mt-6">
        {isLoading && (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2" aria-hidden="true">
            <LoadingSkeleton className="h-52 w-full" />
            <LoadingSkeleton className="h-52 w-full" />
          </div>
        )}

        {!isLoading && error && (
          <div role="alert">
            <EmptyState
              title="Something went wrong"
              description={error}
              action={<Button onClick={() => setReloadKey((key) => key + 1)}>Try again</Button>}
            />
          </div>
        )}

        {!isLoading && !error && scenarios.length === 0 && (
          <EmptyState
            icon={<FolderOpen className="h-6 w-6" />}
            title="No saved comparisons yet"
            description="Save a comparison from a vehicle's Compare Financing Options page to see it here."
            action={
              <Link to="/catalog" className={cn(LINK_BUTTON_BASE, "bg-primary-600 text-white hover:bg-primary-700")}>
                Browse cars
              </Link>
            }
          />
        )}

        {!isLoading && !error && scenarios.length > 0 && (
          <ul className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {scenarios.map((scenario) => (
              <li key={scenario.id}>
                <Card className="flex h-full flex-col gap-4" padding="md">
                  <div className="flex items-start gap-4">
                    <ScenarioPhoto scenario={scenario} vehicle={vehiclesById[scenario.vehicle]} className="w-28 sm:w-36" />
                    <div className="min-w-0 flex-1">
                      <h2 className="font-display text-[1.0625rem] font-bold leading-snug text-ink">{scenario.title}</h2>
                      <p className="mt-0.5 text-small text-ink-muted">{scenario.vehicle_label}</p>
                      <p className="mt-0.5 text-caption text-ink-muted">{scenarioMeta(scenario, bands)}</p>
                    </div>
                  </div>
                  <StoredMonthlies scenario={scenario} />
                  <div className="mt-auto flex flex-wrap items-center gap-2 border-t border-border pt-4">
                    <Link
                      to={`/scenarios/${scenario.id}`}
                      className={cn(LINK_BUTTON_BASE, "border border-border bg-surface text-ink hover:bg-surface-subtle")}
                    >
                      Open
                    </Link>
                    <Button
                      variant="danger-quiet"
                      onClick={() => setConfirmDeleteId(scenario.id)}
                      isLoading={deletingId === scenario.id}
                    >
                      Delete
                    </Button>
                  </div>
                  {deleteErrors[scenario.id] && (
                    <p role="alert" className="text-small text-danger-700">
                      {deleteErrors[scenario.id]}
                    </p>
                  )}
                </Card>
              </li>
            ))}
          </ul>
        )}
      </div>
      <ConfirmDialog
        isOpen={confirmDeleteId !== null}
        title="Delete this saved comparison?"
        message="This cannot be undone."
        confirmLabel="Delete"
        isConfirming={deletingId !== null}
        onConfirm={() => {
          if (confirmDeleteId !== null) void handleDelete(confirmDeleteId);
        }}
        onCancel={() => setConfirmDeleteId(null)}
      />
    </div>
  );
}
