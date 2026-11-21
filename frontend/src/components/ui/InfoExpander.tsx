import type { ReactNode } from "react";
import { Info } from "lucide-react";
import { cn } from "./cn";

// A folded "how is this worked out?" note: a native <details>/<summary>, so
// it opens with a click, Enter or Space and needs no script. The children
// are rendered INSIDE <details>, so the text is always in the page (tests,
// find-in-page and screen readers reach it) even while it is folded - use
// it to quieten a caveat, never to hide one.
//
// Usage: <InfoExpander>Rates are flat rates, the way dealers quote them.</InfoExpander>
//        <InfoExpander summary="What the fee covers" defaultOpen>...</InfoExpander>

interface InfoExpanderProps {
  summary?: string;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
}

export function InfoExpander({
  summary = "How is this calculated?",
  children,
  defaultOpen = false,
  className,
}: InfoExpanderProps) {
  return (
    <details className={cn("group text-small", className)} open={defaultOpen || undefined}>
      <summary
        className={cn(
          "inline-flex cursor-pointer list-none items-center gap-1.5 rounded-control font-semibold text-primary-700",
          "hover:text-primary-800 [&::-webkit-details-marker]:hidden",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2",
        )}
      >
        <Info className="h-4 w-4 shrink-0" aria-hidden="true" />
        {summary}
      </summary>
      <div className="mt-2 text-ink-muted">{children}</div>
    </details>
  );
}
