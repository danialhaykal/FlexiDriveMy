import type { ReactNode } from "react";
import { cn } from "./cn";

// Bordered surface for grouping content - reach for this instead of an
// ad hoc div+border+rounded className. `padding="none"` is for content
// that manages its own edge spacing (e.g. a Table filling the card).
// `tone="highlight"` adds an indigo ring - for the one item a screen
// singles out (e.g. the recommended pathway, as the scoring API says).
//
// Usage: <Card><Card padding="none"><Table>...</Table></Card>
//        <Card tone="highlight">...</Card>

interface CardProps {
  children: ReactNode;
  className?: string;
  padding?: "none" | "md";
  tone?: "default" | "highlight";
}

export function Card({ children, className, padding = "md", tone = "default" }: CardProps) {
  return (
    <div
      data-padding={padding}
      data-tone={tone}
      className={cn(
        "rounded-card border bg-surface shadow-card",
        tone === "highlight" ? "border-primary-600 ring-1 ring-primary-600" : "border-border",
        padding === "md" && "p-6",
        className,
      )}
    >
      {children}
    </div>
  );
}
