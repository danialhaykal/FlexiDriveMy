import { useEffect, useId, useState } from "react";
import type { ReactNode } from "react";
import { Info } from "lucide-react";
import { cn } from "./cn";

// A small "i" button that shows a one-line explanation (FX-3, X13). It opens
// on hover, on keyboard focus and on a click or tap, and closes on Escape, on
// blur and when the pointer leaves; the text is tied to the button with
// aria-describedby while shown, and the button's own label names the topic.
//
// Usage: <InfoTip label="About price tiers">Tier 1 has the highest resale values ...</InfoTip>

interface InfoTipProps {
  label: string;
  children: ReactNode;
  className?: string;
}

export function InfoTip({ label, children, className }: InfoTipProps) {
  const [isOpen, setIsOpen] = useState(false);
  const tipId = useId();

  // Escape dismisses it wherever focus is (a hover-opened tip has no focus).
  useEffect(() => {
    if (!isOpen) return undefined;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setIsOpen(false);
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [isOpen]);

  return (
    <span className={cn("relative inline-flex align-middle", className)}>
      <button
        type="button"
        aria-label={label}
        aria-expanded={isOpen}
        aria-describedby={isOpen ? tipId : undefined}
        onClick={() => setIsOpen(true)}
        onFocus={() => setIsOpen(true)}
        onBlur={() => setIsOpen(false)}
        onMouseEnter={() => setIsOpen(true)}
        onMouseLeave={() => setIsOpen(false)}
        className="rounded-full p-0.5 text-ink-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
      >
        <Info className="h-3.5 w-3.5" aria-hidden="true" />
      </button>
      {isOpen && (
        <span
          role="tooltip"
          id={tipId}
          className="absolute left-0 top-full z-20 mt-1 w-64 max-w-[80vw] rounded-control border border-border bg-surface p-2 text-left text-caption font-normal normal-case tracking-normal text-ink shadow-card"
        >
          {children}
        </span>
      )}
    </span>
  );
}
