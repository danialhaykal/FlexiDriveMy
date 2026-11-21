import { formatCurrency } from "../../lib/formatCurrency";
import { formatSavedDate } from "../../lib/formatSavedDate";
import { mileageBandName } from "../../lib/mileageBandName";
import { bodySegmentLabel } from "../../lib/vehicleLabels";
import type { MileageBandOption } from "../../types/comparisons";
import type { Vehicle } from "../../types/catalog";
import type { Scenario } from "../../types/scenarios";
import { VehiclePhotoPlaceholder } from "../catalog/VehiclePhotoPlaceholder";
import { cn } from "../ui/cn";
import { numeric } from "../ui/tokens";

// Pieces of a saved comparison's summary, shared by the dashboard and My
// Comparisons (redesign UI-4). Every figure comes from the scenario's stored
// payload exactly as saved - nothing is recalculated - and a field an older
// snapshot does not have is shown as "–", never guessed.

const MISSING = "–";

// The car's photo from the catalog list, or the placeholder (also for a car
// that is no longer in the catalog, e.g. archived).
export function ScenarioPhoto({ scenario, vehicle, className }: { scenario: Scenario; vehicle: Vehicle | undefined; className?: string }) {
  return (
    <div className={cn("aspect-[16/10] shrink-0 overflow-hidden rounded-control border border-border bg-surface-subtle", className)}>
      {vehicle?.thumbnail_url ? (
        <img src={vehicle.thumbnail_url} alt="" loading="lazy" className="h-full w-full object-cover" />
      ) : vehicle ? (
        <VehiclePhotoPlaceholder
          brandName={vehicle.brand_name}
          modelName={vehicle.name}
          segmentLabel={bodySegmentLabel(vehicle.body_segment)}
          size="sm"
        />
      ) : (
        <VehiclePhotoPlaceholder brandName={scenario.vehicle_label} modelName="" size="sm" />
      )}
    </div>
  );
}

// "36 months · Standard · Last updated 15 Feb 2026": the band's NAME only (from
// the API's band list), never today's km range - a comparison saved before the
// 22 Oct 2026 band change used other limits. A part the snapshot lacks is left out.
export function scenarioMeta(scenario: Scenario, bands: MileageBandOption[]): string {
  const payload = scenario.payload;
  const parts: string[] = [];
  if (typeof payload?.tenureMonths === "number") parts.push(`${payload.tenureMonths} months`);
  const band = mileageBandName(payload?.mileageBand, bands);
  if (band) parts.push(band);
  parts.push(`Last updated ${formatSavedDate(scenario.updated_at)}`);
  return parts.join(" · ");
}

// The three stored monthly figures, each "–" when the snapshot has none (the
// pathway was unavailable, or an older snapshot lacks the field).
export function StoredMonthlies({ scenario, className }: { scenario: Scenario; className?: string }) {
  const comparison = scenario.payload?.comparison;
  const figures = [
    { label: "Hire Purchase", dot: "bg-pathway-hp", value: comparison?.hire_purchase?.monthly_instalment },
    { label: "GFV Leasing", dot: "bg-pathway-gfv", value: comparison?.gfv_leasing?.monthly_instalment },
    { label: "Subscription", dot: "bg-pathway-sub", value: comparison?.subscription?.monthly_instalment },
  ];
  return (
    <dl className={cn("grid grid-cols-3 gap-3", className)} aria-label="Monthly, as saved">
      {figures.map((figure) => (
        <div key={figure.label} className="flex min-w-0 flex-col gap-0.5">
          <dt className="flex items-center gap-1.5 text-caption font-medium text-ink-muted">
            <span className={cn("h-2 w-2 shrink-0 rounded-[2px]", figure.dot)} aria-hidden="true" />
            <span className="truncate">{figure.label}</span>
          </dt>
          <dd className={cn("text-small font-semibold text-ink", numeric)}>
            {figure.value ? (
              formatCurrency(figure.value)
            ) : (
              <>
                <span aria-hidden="true">{MISSING}</span>
                <span className="sr-only">Not available</span>
              </>
            )}
          </dd>
        </div>
      ))}
    </dl>
  );
}
