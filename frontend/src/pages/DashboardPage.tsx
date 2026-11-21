import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { ArrowRight, Columns3, FolderOpen, Search, Wallet, X } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useCatalogVehiclesById } from "../hooks/useCatalogVehiclesById";
import { useMileageBandOptions } from "../hooks/useMileageBandOptions";
import { listScenarios } from "../api/scenarios";
import { formatSavedDate } from "../lib/formatSavedDate";
import { ADMIN_ONLY_NOTICE } from "../lib/notices";
import type { Scenario } from "../types/scenarios";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { LoadingSkeleton } from "../components/ui/LoadingSkeleton";
import { cn } from "../components/ui/cn";
import { ScenarioPhoto, StoredMonthlies, scenarioMeta } from "../components/scenarios/ScenarioSummary";

// Home page (redesign UI-4): a greeting, "Pick up where you left off" (the
// most recently updated saved comparison, its stored figures exactly as
// saved), three quick actions and up to 5 recent comparisons. Real data from
// the existing F009 endpoint only; no invented metrics. Logout/nav chrome
// lives in AppShell, not here.

const RECENT_SCENARIOS_LIMIT = 5;
// Run 3 fix batch 5 (F-29): a list that could not load is not an empty list.
export const RECENT_LOAD_ERROR = "Could not load your saved comparisons. Please try again.";

// A Link that looks like a Button (primary).
const PRIMARY_LINK_CLASS = cn(
  "inline-flex items-center justify-center gap-2 rounded-control bg-primary-600 px-4 py-2 text-small font-semibold text-white",
  "transition-colors hover:bg-primary-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2",
);
const TEXT_LINK_CLASS = cn(
  "inline-flex items-center gap-1 rounded-control text-small font-semibold text-primary-700 hover:text-primary-800",
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2",
);

interface QuickAction {
  to: string;
  title: string;
  description: string;
  icon: ReactNode;
}

const QUICK_ACTIONS: QuickAction[] = [
  {
    to: "/catalog",
    title: "Browse cars",
    description: "Explore the catalog and start a new comparison.",
    icon: <Search className="h-5 w-5" />,
  },
  {
    to: "/arena",
    title: "Compare cars",
    description: "Put 2 or 3 cars side by side.",
    icon: <Columns3 className="h-5 w-5" />,
  },
  {
    to: "/profile/financial",
    title: "Your financial profile",
    description: "Income, DSR limit and No-Claim Discount.",
    icon: <Wallet className="h-5 w-5" />,
  },
];

function PickUpCard({ scenario, vehiclePhoto, meta }: { scenario: Scenario; vehiclePhoto: ReactNode; meta: string }) {
  return (
    <Card tone="highlight" className="flex flex-col gap-5 sm:flex-row sm:items-start">
      {vehiclePhoto}
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        <div>
          <p className="text-caption font-semibold uppercase tracking-[0.06em] text-primary-700">Pick up where you left off</p>
          <h2 className="mt-1 font-display text-h3 font-bold text-ink">{scenario.title}</h2>
          <p className="mt-0.5 text-small text-ink-muted">{scenario.vehicle_label}</p>
          <p className="mt-0.5 text-caption text-ink-muted">{meta}</p>
        </div>
        <StoredMonthlies scenario={scenario} className="max-w-md" />
        <div>
          <Link to={`/scenarios/${scenario.id}`} className={PRIMARY_LINK_CLASS} aria-label={`Open ${scenario.title}`}>
            Open
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Link>
        </div>
      </div>
    </Card>
  );
}

export function DashboardPage() {
  useDocumentTitle("Dashboard");
  const { user } = useAuth();
  const bands = useMileageBandOptions();
  const [recentScenarios, setRecentScenarios] = useState<Scenario[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const vehiclesById = useCatalogVehiclesById(recentScenarios.length > 0);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setLoadError(null);
    listScenarios()
      .then((data) => {
        if (cancelled) return;
        const sorted = [...data].sort(
          (a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
        );
        setRecentScenarios(sorted.slice(0, RECENT_SCENARIOS_LIMIT));
      })
      .catch(() => {
        if (cancelled) return;
        setRecentScenarios([]);
        setLoadError(RECENT_LOAD_ERROR);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  const latest = recentScenarios[0];
  const location = useLocation();
  const navigate = useNavigate();
  const notice =
    (location.state as { notice?: unknown } | null)?.notice === ADMIN_ONLY_NOTICE ? ADMIN_ONLY_NOTICE : null;

  return (
    <div className="mx-auto max-w-5xl px-4 pb-16 pt-8 sm:pt-10">
      <header>
        <h1 className="text-[1.625rem] font-bold leading-tight text-ink sm:text-[1.875rem]">
          Welcome back, {user?.first_name || user?.email}
        </h1>
        <p className="mt-1 text-small text-ink-muted">Pick up a saved comparison, or start a new one.</p>
      </header>

      {/* FX-2 (item 9, R4-F30f): why a buyer landed here from an admin address. */}
      {notice && (
        <div role="status" className="mt-4 flex items-start justify-between gap-3 rounded-card border border-border bg-surface p-3">
          <p className="text-small text-ink">{notice}</p>
          <button
            type="button"
            aria-label="Dismiss"
            className="rounded-control p-1 text-ink-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
            onClick={() => navigate(location.pathname, { replace: true, state: null })}
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
      )}

      {isLoading && (
        <div className="mt-6 flex flex-col gap-4">
          <LoadingSkeleton className="h-44 w-full" />
        </div>
      )}

      {!isLoading && loadError && (
        <div role="alert" className="mt-6">
          <EmptyState
            title="Something went wrong"
            description={loadError}
            action={<Button onClick={() => setReloadKey((key) => key + 1)}>Try again</Button>}
          />
        </div>
      )}

      {!isLoading && !loadError && latest && (
        <div className="mt-6">
          <PickUpCard
            scenario={latest}
            vehiclePhoto={
              <ScenarioPhoto scenario={latest} vehicle={vehiclesById[latest.vehicle]} className="w-full sm:w-48" />
            }
            meta={scenarioMeta(latest, bands)}
          />
        </div>
      )}

      {!isLoading && !loadError && recentScenarios.length === 0 && (
        <EmptyState
          className="mt-6"
          icon={<FolderOpen className="h-6 w-6" />}
          title="No saved comparisons yet"
          description="Browse the catalog, compare a car's financing options and save it to see it here."
          action={
            <Link to="/catalog" className={PRIMARY_LINK_CLASS}>
              Browse cars
            </Link>
          }
        />
      )}

      <nav aria-label="Quick actions" className="mt-8">
        <ul className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          {QUICK_ACTIONS.map((action) => (
            <li key={action.to}>
              <Link
                to={action.to}
                className={cn(
                  "group flex h-full items-start gap-3 rounded-card border border-border bg-surface p-4 shadow-card transition-shadow hover:shadow-md",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2",
                )}
              >
                <span
                  aria-hidden="true"
                  className="flex h-10 w-10 shrink-0 items-center justify-center rounded-control bg-primary-50 text-primary-700"
                >
                  {action.icon}
                </span>
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className="font-display text-[0.9375rem] font-semibold text-ink group-hover:text-primary-700">
                    {action.title}
                  </span>
                  <span className="text-caption text-ink-muted">{action.description}</span>
                </span>
              </Link>
            </li>
          ))}
        </ul>
      </nav>

      {!isLoading && !loadError && recentScenarios.length > 0 && (
        <section aria-labelledby="recent-comparisons-heading" className="mt-10">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 id="recent-comparisons-heading" className="text-h3 font-bold text-ink">
              Recent comparisons
            </h2>
            <Link to="/scenarios" className={TEXT_LINK_CLASS}>
              See all
              <ArrowRight className="h-4 w-4" aria-hidden="true" />
            </Link>
          </div>
          <Card padding="none" className="mt-3">
            <ul className="divide-y divide-border">
              {recentScenarios.map((scenario) => (
                <li key={scenario.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 py-3 sm:px-5">
                  <div className="min-w-0">
                    <p className="truncate text-small font-semibold text-ink">{scenario.title}</p>
                    <p className="text-caption text-ink-muted">
                      {scenario.vehicle_label} · {formatSavedDate(scenario.updated_at)}
                    </p>
                  </div>
                  <Link
                    to={`/scenarios/${scenario.id}`}
                    className={TEXT_LINK_CLASS}
                    aria-label={`Open ${scenario.title}`}
                  >
                    Open
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        </section>
      )}
    </div>
  );
}
