import type { ReactNode } from "react";
import { cn } from "./cn";
import type { Tone } from "./tokens";

// Small status pill. Reserve positive/warning/danger for genuine
// financial-state meaning (never decorative); use neutral for non-financial
// system status like "service degraded". Two further tones:
//   recommended  solid indigo - only for what the scoring API recommended
//   estimate     amber - a figure that is a planning estimate, not a quote
// Every tone's text is at least 4.5:1 on its own background.
//
// Usage: <Badge tone="positive">On track</Badge>
//        <Badge tone="warning">Approaching DSR limit</Badge>
//        <Badge tone="danger">Threshold exceeded</Badge>
//        <Badge tone="neutral">Service degraded</Badge>
//        <Badge tone="recommended">Recommended</Badge>
//        <Badge tone="estimate">Estimate</Badge>

interface BadgeProps {
  tone?: Tone;
  children: ReactNode;
  className?: string;
}

const TONE_CLASSES: Record<Tone, string> = {
  positive: "bg-positive-50 text-positive-700 border-positive-200",
  warning: "bg-warning-50 text-warning-700 border-warning-200",
  danger: "bg-danger-50 text-danger-700 border-danger-200",
  // Run 1 fix batch 5 (M3): slate-600, not ink-muted (slate-500): the 12 px
  // text on slate-100 was 4.35:1; this is 6.90:1 (WCAG AA needs 4.5:1).
  neutral: "bg-surface-subtle text-slate-600 border-border",
  recommended: "bg-primary-600 text-white border-primary-600",
  estimate: "bg-amber-50 text-amber-800 border-amber-200",
};

export function Badge({ tone = "neutral", children, className }: BadgeProps) {
  return (
    <span
      data-tone={tone}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5",
        "text-caption font-semibold",
        TONE_CLASSES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
