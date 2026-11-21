import { cn } from "./cn";

// Pulsing placeholder block shown while data loads - size it via
// className width/height utilities.
//
// Usage: <LoadingSkeleton variant="text" className="h-4 w-32" /> for a
// text-line placeholder, or variant="circle" for an avatar/logo
// placeholder, or the "block" default for a card/image/table-row area.

interface LoadingSkeletonProps {
  variant?: "text" | "block" | "circle";
  className?: string;
}

const VARIANT_CLASSES: Record<NonNullable<LoadingSkeletonProps["variant"]>, string> = {
  text: "h-4 rounded",
  block: "rounded-md",
  circle: "rounded-full",
};

export function LoadingSkeleton({ variant = "block", className }: LoadingSkeletonProps) {
  return (
    <div
      data-variant={variant}
      role="status"
      aria-label="Loading"
      className={cn("animate-pulse bg-surface-subtle", VARIANT_CLASSES[variant], className)}
    />
  );
}
