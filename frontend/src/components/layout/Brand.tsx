import { CarFront } from "lucide-react";
import { cn } from "../ui/cn";

// The FlexiDriveMy mark: a small indigo square with a car, and the name in
// the display face - white on the navy sidebar/panel, ink on white.
export function Brand({ onDark, className }: { onDark: boolean; className?: string }) {
  return (
    <span className={cn("flex items-center gap-2", className)}>
      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-primary-600">
        <CarFront className="h-4 w-4 text-white" aria-hidden="true" />
      </span>
      <span className={cn("font-display text-[1.125rem] font-extrabold", onDark ? "text-white" : "text-ink")}>
        FlexiDriveMy
      </span>
    </span>
  );
}
