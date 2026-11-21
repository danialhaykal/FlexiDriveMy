import { Fragment, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchVehicleReadiness } from "../api/readiness";
import { useCatalogVehiclesById } from "../hooks/useCatalogVehiclesById";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import type { ReadinessCheckStatus, VehicleReadiness } from "../types/readiness";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { InfoExpander } from "../components/ui/InfoExpander";
import { PageHeader } from "../components/ui/PageHeader";
import { StatFigure } from "../components/ui/StatFigure";
import { Table } from "../components/ui/Table";
import { cn } from "../components/ui/cn";
import { VehiclePhotoPlaceholder } from "../components/catalog/VehiclePhotoPlaceholder";

// Admin: after adding any car or brand, can the app fully price it? Every row
// and check comes from GET /api/admin/vehicle-readiness/, which calls the same
// code the screens use - this page only displays it, and does no calculation.
// Redesign UI-6b: a header, three tiles counted from the rows the API returned
// (no new rule), the "Needs attention only" toggle, and each car with its photo.

const GENERIC_ERROR = "Could not load vehicle readiness. Please try again.";

const CHECK_BADGE: Record<
  ReadinessCheckStatus,
  { tone: "positive" | "danger" | "warning" | "neutral"; text: string }
> = {
  ok: { tone: "positive", text: "OK" },
  missing: { tone: "danger", text: "Missing" },
  warning: { tone: "warning", text: "Recommended" },
  info: { tone: "neutral", text: "Info" },
};

export function VehicleReadinessPage() {
  useDocumentTitle("Vehicle Readiness");
  const [vehicles, setVehicles] = useState<VehicleReadiness[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [needsAttentionOnly, setNeedsAttentionOnly] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  // Fetched ONCE per visit (and again only on Retry): the "Needs attention
  // only" filter works on the report already loaded, so toggling it never
  // re-runs the (slow) check.
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    fetchVehicleReadiness()
      .then((data) => {
        if (!cancelled) setVehicles(data);
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
  }, [attempt]);

  const shown = needsAttentionOnly ? vehicles.filter((v) => v.status === "needs_attention") : vehicles;
  // The car photos, from the catalog list (a car not found keeps the placeholder).
  const catalogById = useCatalogVehiclesById(vehicles.length > 0);
  // Counted from the rows the API returned - nothing re-decided here.
  const readyCount = vehicles.filter((v) => v.status === "ready").length;
  const attentionCount = vehicles.filter((v) => v.status === "needs_attention").length;
  const recommendedTotal = vehicles.reduce((sum, v) => sum + v.warning_count, 0);

  return (
    <div className="mx-auto max-w-6xl px-4 pb-16 pt-8 sm:pt-10">
      <PageHeader title="Vehicle readiness" subtitle="Can the app fully price each car?" />
      <InfoExpander summary="What is checked" className="mt-2">
        Whether the app can fully price each car: its specs, running costs, interest rate, residuals,
        subscription and contract terms. A car marked "Needs attention" is missing something the
        app needs; "Recommended" items never block pricing.
      </InfoExpander>

      {/* Each car runs about a hundred checks, so this takes a few seconds: say
          so, rather than leaving only the intro on screen. */}
      {isLoading && (
        <div role="status" className="mt-6 flex flex-col gap-3">
          <p className="text-small font-medium text-ink">Checking every car - this can take a few seconds...</p>
          <div aria-hidden="true" className="h-12 w-full animate-pulse rounded-lg bg-surface-subtle" />
          <div aria-hidden="true" className="h-12 w-full animate-pulse rounded-lg bg-surface-subtle" />
          <div aria-hidden="true" className="h-12 w-full animate-pulse rounded-lg bg-surface-subtle" />
        </div>
      )}

      {!isLoading && error && (
        <EmptyState
          className="mt-6"
          title="Readiness unavailable"
          description={error}
          action={
            <Button variant="secondary" onClick={() => setAttempt((count) => count + 1)}>
              Retry
            </Button>
          }
        />
      )}

      {!isLoading && !error && (
        <>
          {/* One row of three at every width (compact on a phone). */}
          <section aria-label="Summary" className="mt-6 grid grid-cols-3 gap-3 sm:gap-4">
            <Card padding="none" className="p-3 sm:p-5">
              <StatFigure label="Ready" value={readyCount} size="money-sm" />
            </Card>
            <Card padding="none" className="p-3 sm:p-5">
              <StatFigure label="Needs attention" value={attentionCount} size="money-sm" />
            </Card>
            <Card padding="none" className="p-3 sm:p-5">
              <StatFigure label="Recommended items" value={recommendedTotal} size="money-sm" />
            </Card>
          </section>

          <Card padding="none" className="mt-6">
            <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 sm:px-6">
              <h2 className="text-h3 font-semibold text-ink">Cars</h2>
              {/* A toggle: a real checkbox (named by its label), drawn as a switch. */}
              <label className="inline-flex cursor-pointer items-center gap-2.5 text-small font-medium text-ink">
                <input
                  type="checkbox"
                  role="switch"
                  checked={needsAttentionOnly}
                  onChange={(e) => setNeedsAttentionOnly(e.target.checked)}
                  className="peer sr-only"
                />
                <span
                  aria-hidden="true"
                  className={cn(
                    "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors",
                    "peer-focus-visible:ring-2 peer-focus-visible:ring-primary-500 peer-focus-visible:ring-offset-2",
                    needsAttentionOnly ? "bg-primary-600" : "bg-slate-500",
                  )}
                >
                  <span
                    className={cn(
                      "absolute h-4 w-4 rounded-full bg-white shadow transition-transform",
                      needsAttentionOnly ? "translate-x-[18px]" : "translate-x-0.5",
                    )}
                  />
                </span>
                Needs attention only
              </label>
            </div>
            <Table>
              <Table.Head>
                <Table.Row>
                  <Table.HeaderCell>Car</Table.HeaderCell>
                  <Table.HeaderCell>Status</Table.HeaderCell>
                  <Table.HeaderCell numeric>Items missing</Table.HeaderCell>
                  <Table.HeaderCell numeric>Recommended items</Table.HeaderCell>
                  <Table.HeaderCell>
                    <span className="sr-only">Actions</span>
                  </Table.HeaderCell>
                </Table.Row>
              </Table.Head>
              <Table.Body>
                {shown.map((vehicle) => {
                  const isExpanded = expandedId === vehicle.vehicle_id;
                  const catalogCar = catalogById[vehicle.vehicle_id];
                  return (
                    <Fragment key={vehicle.vehicle_id}>
                      <Table.Row>
                        <Table.Cell>
                          <span className="flex items-center gap-3">
                            <span className="h-9 w-14 shrink-0 overflow-hidden rounded-control border border-border bg-surface-subtle">
                              {catalogCar?.thumbnail_url ? (
                                <img src={catalogCar.thumbnail_url} alt="" loading="lazy" className="h-full w-full object-cover" />
                              ) : (
                                <VehiclePhotoPlaceholder brandName={vehicle.label} modelName="" size="xs" />
                              )}
                            </span>
                            <span className="font-medium">{vehicle.label}</span>
                          </span>
                        </Table.Cell>
                        <Table.Cell>
                          {vehicle.status === "ready" ? (
                            <Badge tone="positive">Ready</Badge>
                          ) : (
                            <Badge tone="danger">Needs attention</Badge>
                          )}
                        </Table.Cell>
                        <Table.Cell numeric>{vehicle.missing_count}</Table.Cell>
                        <Table.Cell numeric>{vehicle.warning_count}</Table.Cell>
                        <Table.Cell>
                          <div className="flex items-center justify-end gap-2">
                            <Button
                              variant="ghost"
                              aria-expanded={isExpanded}
                              aria-label={`${isExpanded ? "Hide" : "Show"} details for ${vehicle.label}`}
                              onClick={() => setExpandedId(isExpanded ? null : vehicle.vehicle_id)}
                            >
                              {isExpanded ? "Hide details" : "Details"}
                            </Button>
                            <Link
                              to={`/admin/fleet?edit=${vehicle.vehicle_id}`}
                              aria-label={`Edit vehicle ${vehicle.label}`}
                              className="whitespace-nowrap rounded-control text-small font-semibold text-primary-700 hover:text-primary-800 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
                            >
                              Edit vehicle
                            </Link>
                          </div>
                        </Table.Cell>
                      </Table.Row>
                      {isExpanded && (
                        <Table.Row className="bg-page-bg">
                          <Table.Cell colSpan={5}>
                            <ul className="flex flex-col gap-2 py-1">
                              {vehicle.checks.map((check) => (
                                <li key={check.key} className="flex flex-wrap items-start gap-2 text-small">
                                  <Badge tone={CHECK_BADGE[check.status].tone}>{CHECK_BADGE[check.status].text}</Badge>
                                  <span className="font-medium text-ink">{check.label}</span>
                                  <span className="text-ink-muted">{check.detail}</span>
                                </li>
                              ))}
                            </ul>
                          </Table.Cell>
                        </Table.Row>
                      )}
                    </Fragment>
                  );
                })}
              </Table.Body>
            </Table>
            {shown.length === 0 && (
              <EmptyState
                className="border-0"
                title={needsAttentionOnly ? "Every car is ready" : "No active cars to check"}
              />
            )}
          </Card>
        </>
      )}
    </div>
  );
}
