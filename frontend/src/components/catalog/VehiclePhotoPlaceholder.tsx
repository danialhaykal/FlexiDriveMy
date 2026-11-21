import { CarFront } from "lucide-react";
import { cn } from "../ui/cn";

// A deliberate stand-in when a car has no photo: a soft gradient, a car icon,
// the body segment (when given) and "Photo coming soon". No stock photos,
// nothing guessed and no brand logos (those are copyrighted). role="img" with
// the exact label tells a screen reader what is missing.

interface VehiclePhotoPlaceholderProps {
  brandName: string;
  modelName: string;
  // The body segment's display label (e.g. "SUV"), when the caller has it.
  segmentLabel?: string;
  // "lg" for the vehicle page's hero; "md" (default) for a catalog card; "sm"
  // for a small thumbnail (a picker tile, a saved-comparison card); "xs" for a
  // table thumbnail (the icon only - the label still says what is missing).
  size?: "xs" | "sm" | "md" | "lg";
}

const ICON_SIZE: Record<NonNullable<VehiclePhotoPlaceholderProps["size"]>, string> = {
  xs: "h-5 w-5",
  sm: "h-8 w-8",
  md: "h-12 w-12",
  lg: "h-20 w-20",
};

export function VehiclePhotoPlaceholder({ brandName, modelName, segmentLabel, size = "md" }: VehiclePhotoPlaceholderProps) {
  return (
    <div
      role="img"
      aria-label={`No photo available for ${brandName} ${modelName}`.trim()}
      className={cn(
        "flex h-full w-full flex-col items-center justify-center bg-gradient-to-br from-page-bg via-surface-subtle to-border text-center",
        size === "xs" ? "p-0" : size === "sm" ? "gap-1 p-2" : "gap-2 p-4",
      )}
    >
      <CarFront aria-hidden="true" className={cn("text-ink-muted", ICON_SIZE[size])} strokeWidth={1.5} />
      {size !== "xs" && segmentLabel && (
        <span aria-hidden="true" className="text-caption font-semibold uppercase tracking-[0.07em] text-ink-muted">
          {segmentLabel}
        </span>
      )}
      {size !== "xs" && (
        <span aria-hidden="true" className={cn("text-ink-muted", size === "sm" ? "text-caption" : "text-small")}>
          Photo coming soon
        </span>
      )}
    </div>
  );
}
