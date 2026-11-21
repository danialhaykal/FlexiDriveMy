import type { ReactNode } from "react";
import { cn } from "./cn";
import { numeric } from "./tokens";

// A labelled figure: a small capitalised label over a value in Inter with
// tabular digits, and an optional muted suffix ("/ month"). It only SHOWS a
// value the API returned - never compute a figure to pass in here.
//
//   size="money"     headline figure (32 px)
//   size="money-sm"  smaller headline (26 px)
//   size="default"   a supporting fact (16 px)
//
// Usage: <StatFigure label="Monthly" value="RM 7,257.38" suffix="/ month" size="money" />

interface StatFigureProps {
  label: ReactNode;
  value: ReactNode;
  suffix?: ReactNode;
  size?: "money" | "money-sm" | "default";
  className?: string;
}

const VALUE_SIZE: Record<NonNullable<StatFigureProps["size"]>, string> = {
  money: "text-money font-bold tracking-tight",
  "money-sm": "text-money-sm font-bold tracking-tight",
  default: "text-body font-semibold",
};

export function StatFigure({ label, value, suffix, size = "default", className }: StatFigureProps) {
  return (
    <div className={cn("flex flex-col gap-1", className)} data-size={size}>
      <span className="text-[0.6875rem] font-semibold uppercase tracking-[0.06em] text-ink-muted">{label}</span>
      <span className={cn("text-ink", numeric, VALUE_SIZE[size])}>
        {value}
        {suffix && <span className="ml-1 text-[0.8125rem] font-medium tracking-normal text-ink-muted">{suffix}</span>}
      </span>
    </div>
  );
}
