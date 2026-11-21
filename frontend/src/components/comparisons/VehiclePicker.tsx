import { Check } from "lucide-react";
import { cn } from "../ui/cn";
import { Card } from "../ui/Card";
import { numeric } from "../ui/tokens";
import { formatCurrency } from "../../lib/formatCurrency";
import { bodySegmentLabel } from "../../lib/vehicleLabels";
import { VehiclePhotoPlaceholder } from "../catalog/VehiclePhotoPlaceholder";
import { PhotoCreditLine } from "../catalog/PhotoCreditLine";
import type { Vehicle } from "../../types/catalog";

// The Arena's vehicle picker: a grid of car tiles (redesign UI-4), each one a
// real checkbox underneath - so it is reached with Tab, toggled with Space,
// announced as checked/not checked, and named by the car. Disabled once
// maxSelections is reached. No search/filter/pagination UI: the catalog is a
// small curated set.
//
// Usage: <VehiclePicker vehicles={vehicles} selectedIds={selectedIds}
//   onChange={setSelectedIds} maxSelections={3} />

interface VehiclePickerProps {
  vehicles: Vehicle[];
  selectedIds: number[];
  onChange: (ids: number[]) => void;
  maxSelections: number;
}

export function VehiclePicker({ vehicles, selectedIds, onChange, maxSelections }: VehiclePickerProps) {
  function toggle(id: number) {
    if (selectedIds.includes(id)) {
      onChange(selectedIds.filter((selectedId) => selectedId !== id));
    } else if (selectedIds.length < maxSelections) {
      onChange([...selectedIds, id]);
    }
  }

  return (
    <Card>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="text-h3 font-semibold text-ink">Select vehicles to compare</h2>
        <p className="text-small font-medium text-ink-muted" aria-live="polite">
          {selectedIds.length} of {maxSelections} selected
        </p>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-4">
        {vehicles.map((vehicle) => {
          const isSelected = selectedIds.includes(vehicle.id);
          const isDisabled = !isSelected && selectedIds.length >= maxSelections;
          const name = `${vehicle.brand_name} ${vehicle.name} ${vehicle.trim}`;
          return (
            <label
              key={vehicle.id}
              className={cn(
                "relative flex flex-col overflow-hidden rounded-card border bg-surface transition-colors",
                "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-primary-500 has-[:focus-visible]:ring-offset-2",
                isSelected ? "border-primary-600 ring-1 ring-primary-600" : "border-border hover:border-primary-300",
                isDisabled ? "cursor-not-allowed opacity-50" : "cursor-pointer",
              )}
            >
              <input
                type="checkbox"
                checked={isSelected}
                disabled={isDisabled}
                onChange={() => toggle(vehicle.id)}
                aria-label={name}
                className="peer sr-only"
              />
              <div className="aspect-[16/10] w-full overflow-hidden bg-surface-subtle">
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
              {/* The check mark: a filled circle when selected, an empty ring when not. */}
              <span
                aria-hidden="true"
                className={cn(
                  "absolute right-2 top-2 flex h-6 w-6 items-center justify-center rounded-full border-2 shadow-sm",
                  isSelected ? "border-primary-600 bg-primary-600 text-white" : "border-white bg-surface/80 text-transparent",
                )}
              >
                <Check className="h-3.5 w-3.5" strokeWidth={3} />
              </span>
              <span className="flex flex-1 flex-col gap-1 p-3">
                <span className="text-small font-semibold leading-snug text-ink">{name}</span>
                <span className={cn("text-caption text-ink-muted", numeric)}>{formatCurrency(vehicle.msrp)}</span>
              </span>
            </label>
          );
        })}
      </div>
      {/* FX-2 (item 8) */}
      <div className="mt-4">
        <PhotoCreditLine thumbnailUrls={vehicles.map((vehicle) => vehicle.thumbnail_url)} />
      </div>
    </Card>
  );
}
