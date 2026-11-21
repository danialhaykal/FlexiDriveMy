import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import type { ArenaEntry, ArenaResult, ArenaWinner } from "../../types/arena";
import type { Vehicle } from "../../types/catalog";
import type { MileageBand } from "../../types/comparisons";
import { formatCurrency } from "../../lib/formatCurrency";
import { bodySegmentLabel } from "../../lib/vehicleLabels";
import { useMediaQuery } from "../../hooks/useMediaQuery";
import { Badge } from "../ui/Badge";
import { Card } from "../ui/Card";
import { Table } from "../ui/Table";
import { cn } from "../ui/cn";
import { numeric } from "../ui/tokens";
import { VehiclePhotoPlaceholder } from "../catalog/VehiclePhotoPlaceholder";

// Sprint 10's multi-vehicle "Arena" - one COLUMN per vehicle from md (car
// shoppers scan columns), one CARD per vehicle below md (redesign UI-4). The
// rows are each pathway's monthly instalment plus net TCO. A vehicle whose own
// config is missing shows its error instead of figures (that vehicle's own
// "ok: false" entry - the rest of the arena is unaffected). A winning figure
// gets a "Best" badge, matching winners exactly as computed server-side
// (apps.comparisons.arena.compute_arena_winners) - this component never picks
// a winner itself. The two layouts are switched by a media query rather than
// both rendered, so every figure is in the page once.
//
// Usage: <ArenaTable arena={arena} vehiclesById={vehiclesById}
//          compareInputs={{ tenureMonths, mileageBand, downpayment }} />

// The inputs the arena was fetched with: when given, each car's name links to
// its own compare page on the same three inputs.
export interface ArenaCompareInputs {
  tenureMonths: number;
  mileageBand: MileageBand;
  downpayment: string;
}

interface ArenaTableProps {
  arena: ArenaResult;
  vehiclesById: Record<number, Vehicle | undefined>;
  compareInputs?: ArenaCompareInputs;
}

// From md (768 px) the table; below it, one card per car.
const TABLE_MEDIA_QUERY = "(min-width: 768px)";

function vehicleLabel(vehicle: Vehicle | undefined): string {
  if (!vehicle) return "Vehicle";
  return `${vehicle.brand_name} ${vehicle.name} ${vehicle.trim}`;
}

export function arenaCompareUrl(vehicleId: number, inputs: ArenaCompareInputs): string {
  const params = new URLSearchParams({
    tenure: String(inputs.tenureMonths),
    mileage: inputs.mileageBand,
    downpayment: inputs.downpayment,
  });
  return `/catalog/${vehicleId}/compare?${params.toString()}`;
}

interface ArenaRowDef {
  label: string;
  winner: ArenaWinner | null;
  getValue: (entry: ArenaEntry) => string | null;
  // Only consulted when entry.ok is true but getValue returned null -
  // that's a per-pathway gap (e.g. GFV unavailable at this tenure/
  // mileage band), not the vehicle-level failure `entry.error` covers.
  getUnavailableReason?: (entry: ArenaEntry) => string | null;
  note?: (entry: ArenaEntry) => ReactNode;
}

function arenaRows(arena: ArenaResult): ArenaRowDef[] {
  const { winners } = arena;
  return [
    {
      label: "Hire Purchase (monthly)",
      winner: winners.cheapest_hp,
      getValue: (entry) => entry.comparison?.hire_purchase?.monthly_instalment ?? null,
      getUnavailableReason: (entry) => entry.comparison?.unavailable.hire_purchase ?? null,
    },
    {
      label: "GFV Leasing (monthly)",
      winner: winners.cheapest_gfv,
      getValue: (entry) => entry.comparison?.gfv_leasing?.monthly_instalment ?? null,
      getUnavailableReason: (entry) => entry.comparison?.unavailable.gfv_leasing ?? null,
    },
    {
      label: "Subscription (monthly)",
      winner: winners.cheapest_subscription,
      getValue: (entry) => entry.comparison?.subscription?.monthly_instalment ?? null,
      getUnavailableReason: (entry) => entry.comparison?.unavailable.subscription ?? null,
    },
    {
      // QA audit M24: this TCO figure only ever covers the Hire
      // Purchase pathway (build_tco_report is HP-only) - labeling
      // fix, not a new GFV/Subscription TCO feature (that's a
      // later-batch scope gap).
      label: "TCO (Hire Purchase, net, 60 months)",
      winner: winners.lowest_tco,
      getValue: (entry) => entry.tco_net,
      getUnavailableReason: (entry) => entry.tco_unavailable_reason,
      // Run 2 fix batch 3: a car the model doesn't cover (electric...) is on the
      // estimated curve by design - said plainly, not as a fault. "Degraded" stays
      // for a model that isn't available and for responses without forecast_source.
      note: (entry) => {
        if (!entry.model_degraded) return undefined;
        if (entry.forecast_source === "estimated_curve_unsupported") {
          return (
            <Badge tone="neutral" className="rounded-md">
              Estimated curve - sits out of the TCO race (no machine-learning forecast for this car)
            </Badge>
          );
        }
        return (
          <Badge tone="warning" className="rounded-md">
            Degraded - excluded from TCO race
          </Badge>
        );
      },
    },
  ];
}

// The one reason to show under a row's label instead of in every cell: only
// when every car that has figures is "Not available" in this row for the SAME
// reason (the API's own text, compared as given).
function sharedUnavailableReason(row: ArenaRowDef, results: ArenaEntry[]): string | null {
  const okEntries = results.filter((entry) => entry.ok);
  if (okEntries.length < 2 || okEntries.some((entry) => row.getValue(entry) !== null)) return null;
  const reasons = okEntries.map((entry) => row.getUnavailableReason?.(entry) ?? null);
  const [first] = reasons;
  return first && reasons.every((reason) => reason === first) ? first : null;
}

// --- shared pieces -----------------------------------------------------------

function CarPhoto({ vehicle, className }: { vehicle: Vehicle | undefined; className?: string }) {
  if (!vehicle) return null;
  return (
    <div className={cn("aspect-[16/10] overflow-hidden rounded-control border border-border bg-surface-subtle", className)}>
      {vehicle.thumbnail_url ? (
        <img src={vehicle.thumbnail_url} alt="" loading="lazy" className="h-full w-full object-cover" />
      ) : (
        <VehiclePhotoPlaceholder
          brandName={vehicle.brand_name}
          modelName={vehicle.name}
          segmentLabel={bodySegmentLabel(vehicle.body_segment)}
          size="sm"
        />
      )}
    </div>
  );
}

function CarName({ entry, vehicle, compareInputs }: { entry: ArenaEntry; vehicle: Vehicle | undefined; compareInputs?: ArenaCompareInputs }) {
  // Run 3 fix batch 5 (F-25): a car's name keeps its own case ("320i", not "320I").
  const label = vehicleLabel(vehicle);
  const className = "font-display text-[0.9375rem] font-semibold leading-snug text-ink normal-case";
  if (!compareInputs) return <span className={className}>{label}</span>;
  return (
    <Link
      to={arenaCompareUrl(entry.vehicle_id, compareInputs)}
      className={cn(
        className,
        "rounded-control underline-offset-2 hover:text-primary-700 hover:underline",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2",
      )}
    >
      {label}
    </Link>
  );
}

function CarStatus({ entry }: { entry: ArenaEntry }) {
  // Run 3 fix batch 4 (F-21): the server's own wording - "Not available at this
  // downpayment" when no pathway is offered for this car.
  if (!entry.ok) {
    return (
      <div className="flex flex-col items-start gap-1">
        <Badge tone="danger">Unavailable</Badge>
        <span className="text-caption font-normal text-ink-muted">{entry.error}</span>
      </div>
    );
  }
  const status = entry.status_label ?? "Available";
  return <Badge tone={status === "Available" ? "positive" : "danger"}>{status}</Badge>;
}

interface ArenaValueProps {
  row: ArenaRowDef;
  entry: ArenaEntry;
  // Leave the reason out of the cell (it is shown once under the row label).
  hideReason?: boolean;
}

function ArenaValue({ row, entry, hideReason = false }: ArenaValueProps) {
  // QA audit L10: every vehicle_id in tied_with gets the "Best" badge,
  // not just winner_id - a tie no longer silently favors one vehicle.
  const isTie = (row.winner?.tied_with.length ?? 0) > 1;
  const value = entry.ok ? row.getValue(entry) : null;
  const isWinner = entry.ok && (row.winner?.tied_with.includes(entry.vehicle_id) ?? false);

  if (!entry.ok) return <span className="text-ink-subtle">—</span>;
  if (value === null) {
    const reason = hideReason ? null : row.getUnavailableReason?.(entry) ?? null;
    return (
      <div className="flex flex-col items-start gap-1">
        <span className="font-normal text-ink-subtle">Not available</span>
        {reason && <span className="text-caption font-normal text-ink-muted">{reason}</span>}
      </div>
    );
  }
  return (
    <div className="flex flex-col items-start gap-1">
      <div className="flex flex-wrap items-center gap-2">
        <span className={cn(numeric, isWinner ? "font-semibold text-ink" : undefined)}>{formatCurrency(value)}</span>
        {isWinner && <Badge tone="recommended">{isTie ? "Best (tied)" : "Best"}</Badge>}
      </div>
      {row.note?.(entry)}
    </div>
  );
}

// --- md and up: one column per car ---------------------------------------------

function ArenaColumns({ arena, vehiclesById, compareInputs }: ArenaTableProps) {
  const { results } = arena;
  const rows = arenaRows(arena);
  return (
    <Card padding="none">
      {/* Fixed layout: every car's column is the same width, and its photo, name and
          figures all start at the same left edge, so a column reads as one car. */}
      <Table className="table-fixed">
        <Table.Head>
          <Table.Row>
            <Table.HeaderCell className="w-44 align-bottom lg:w-52">Pathway</Table.HeaderCell>
            {results.map((entry) => {
              const vehicle = vehiclesById[entry.vehicle_id];
              return (
                <Table.HeaderCell key={entry.vehicle_id} className="align-top">
                  <div className="flex flex-col items-start gap-2">
                    <CarPhoto vehicle={vehicle} className="w-full max-w-[11rem]" />
                    <CarName entry={entry} vehicle={vehicle} compareInputs={compareInputs} />
                    <CarStatus entry={entry} />
                  </div>
                </Table.HeaderCell>
              );
            })}
          </Table.Row>
        </Table.Head>
        <Table.Body>
          {rows.map((row) => {
            const sharedReason = sharedUnavailableReason(row, results);
            return (
              <Table.Row key={row.label}>
                <Table.Cell className="align-top">
                  <span className="font-medium">{row.label}</span>
                  {sharedReason && <p className="mt-1 text-caption text-ink-muted">{sharedReason}</p>}
                </Table.Cell>
                {results.map((entry) => (
                  <Table.Cell key={entry.vehicle_id} className="align-top font-medium">
                    <ArenaValue row={row} entry={entry} hideReason={sharedReason !== null} />
                  </Table.Cell>
                ))}
              </Table.Row>
            );
          })}
        </Table.Body>
      </Table>
    </Card>
  );
}

// --- below md: one card per car ------------------------------------------------

function ArenaCards({ arena, vehiclesById, compareInputs }: ArenaTableProps) {
  const rows = arenaRows(arena);
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      {arena.results.map((entry) => {
        const vehicle = vehiclesById[entry.vehicle_id];
        return (
          <article key={entry.vehicle_id} aria-label={vehicleLabel(vehicle)}>
            <Card className="flex h-full flex-col gap-4" padding="md">
              <div className="flex flex-col items-start gap-2">
                <CarPhoto vehicle={vehicle} className="w-full" />
                <CarName entry={entry} vehicle={vehicle} compareInputs={compareInputs} />
                <CarStatus entry={entry} />
              </div>
              {entry.ok && (
                <dl className="flex flex-col divide-y divide-border text-small">
                  {rows.map((row) => (
                    <div key={row.label} className="flex flex-col gap-1 py-2.5 first:pt-0 last:pb-0">
                      <dt className="text-caption font-medium text-ink-muted">{row.label}</dt>
                      <dd className="font-medium text-ink">
                        <ArenaValue row={row} entry={entry} />
                      </dd>
                    </div>
                  ))}
                </dl>
              )}
            </Card>
          </article>
        );
      })}
    </div>
  );
}

export function ArenaTable(props: ArenaTableProps) {
  // jsdom (tests) has no matchMedia: the table is the default there.
  const isWide = useMediaQuery(TABLE_MEDIA_QUERY, true);
  return isWide ? <ArenaColumns {...props} /> : <ArenaCards {...props} />;
}
