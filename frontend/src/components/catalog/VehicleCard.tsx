import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import type { Vehicle } from "../../types/catalog";
import { bodySegmentLabel, formatPowerKw } from "../../lib/vehicleLabels";
import { numeric } from "../ui/tokens";
import { VehiclePhotoPlaceholder } from "./VehiclePhotoPlaceholder";

interface VehicleCardProps {
  vehicle: Vehicle;
}

// Display formatting only (thousands separators) - the digits themselves
// come straight from the API and are never recomputed here (the project spec:
// only Python performs monetary arithmetic).
function formatMsrp(msrp: string): string {
  const value = Number(msrp);
  if (Number.isNaN(value)) return msrp;
  return `RM ${value.toLocaleString("en-MY", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function VehicleCard({ vehicle }: VehicleCardProps) {
  // Power, powertrain and body segment as chips under the price; a missing
  // value is simply left out, never shown as "null" or guessed.
  const segment = bodySegmentLabel(vehicle.body_segment);
  const chips = [formatPowerKw(vehicle.engine_capacity_kw), vehicle.powertrain_phrase ?? "", segment].filter(Boolean);
  return (
    <Link
      to={`/catalog/${vehicle.id}`}
      data-testid="vehicle-card"
      className="group flex flex-col overflow-hidden rounded-card border border-border bg-surface shadow-card transition-shadow hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2"
    >
      <div className="aspect-[16/10] w-full overflow-hidden bg-surface-subtle">
        {vehicle.thumbnail_url ? (
          <img
            src={vehicle.thumbnail_url}
            alt={`${vehicle.brand_name} ${vehicle.name}`}
            loading="lazy"
            className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.02]"
          />
        ) : (
          <VehiclePhotoPlaceholder brandName={vehicle.brand_name} modelName={vehicle.name} segmentLabel={segment} />
        )}
      </div>
      <div className="flex flex-1 flex-col p-4">
        <p className="text-small text-ink-muted">
          {vehicle.brand_name}
          {/* Shown whenever the car has one; a missing year is simply left out
              (and flagged to admins in Vehicle Readiness), never guessed. */}
          {vehicle.model_year ? ` · ${vehicle.model_year}` : ""}
        </p>
        <h3 className="mt-0.5 font-display text-[1.0625rem] font-semibold leading-snug text-ink">
          {vehicle.name} {vehicle.trim}
        </h3>
        <p className={`mt-2 text-[1.125rem] font-semibold text-ink ${numeric}`}>{formatMsrp(vehicle.msrp)}</p>
        {chips.length > 0 && (
          <ul className="mt-3 flex flex-wrap gap-1.5" aria-label="Specs">
            {chips.map((chip) => (
              <li
                key={chip}
                className="rounded-full border border-border bg-page-bg px-2.5 py-0.5 text-caption font-medium text-ink-muted"
              >
                {chip}
              </li>
            ))}
          </ul>
        )}
        <span className="mt-auto flex items-center gap-1 pt-4 text-small font-semibold text-primary-700">
          View car
          <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" aria-hidden="true" />
        </span>
      </div>
    </Link>
  );
}
