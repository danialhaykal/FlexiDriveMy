import type { ReactNode } from "react";
import { cn } from "./cn";

// Centered placeholder for a list/table with nothing to show.
//
// Usage: <EmptyState title="No vehicles match your filters"
//   description="Try broadening your filter parameters."
//   action={<Button onClick={resetFilters}>Reset all filters</Button>} />
//        <EmptyState icon={<Columns3 className="h-6 w-6" />} title="..." />

interface EmptyStateProps {
  title: string;
  description?: string;
  action?: ReactNode;
  // An optional lucide icon shown in a soft circle above the title (decorative).
  icon?: ReactNode;
  className?: string;
}

export function EmptyState({ title, description, action, icon, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex flex-col items-center gap-2 rounded-card border border-dashed border-border p-10 text-center",
        className,
      )}
    >
      {icon && (
        <span
          aria-hidden="true"
          className="mb-1 flex h-12 w-12 items-center justify-center rounded-full bg-primary-50 text-primary-700"
        >
          {icon}
        </span>
      )}
      <p className="text-h3 font-semibold text-ink">{title}</p>
      {description && <p className="text-small text-ink-muted">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  );
}
