import { useEffect, useId, useRef } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { cn } from "./cn";

// A side panel (redesign UI-6b): from the right on a desktop, a full-screen
// sheet on a phone. A modal dialog: focus moves into it when it opens, Tab
// stays inside it, Escape / the Close button / a click on the backdrop close
// it, and focus returns to whatever opened it.
//
// Usage: <Drawer isOpen={row !== null} title="Audit entry" onClose={() => setRow(null)}>...</Drawer>

interface DrawerProps {
  isOpen: boolean;
  title: string;
  // A short line under the title (e.g. the time and resource).
  subtitle?: ReactNode;
  onClose: () => void;
  children: ReactNode;
}

export function Drawer({ isOpen, title, subtitle, onClose, children }: DrawerProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const titleId = useId();

  useEffect(() => {
    if (!isOpen) return;
    returnFocusRef.current = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    return () => {
      returnFocusRef.current?.focus?.();
    };
  }, [isOpen]);

  if (!isOpen) return null;

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(
      panelRef.current?.querySelectorAll<HTMLElement>(
        'button, [href], input, select, textarea, summary, [tabindex]:not([tabindex="-1"])',
      ) ?? [],
    ).filter((el) => !el.hasAttribute("disabled"));
    if (focusable.length === 0) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return createPortal(
    <div className="fixed inset-0 z-50 flex justify-end" onKeyDown={onKeyDown}>
      <div className="absolute inset-0 bg-ink/40" aria-hidden="true" onClick={onClose} />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={cn(
          "relative flex h-full w-full flex-col bg-surface shadow-xl",
          "sm:max-w-[34rem] sm:border-l sm:border-border",
        )}
      >
        <div className="flex items-start justify-between gap-4 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <h2 id={titleId} className="text-h3 font-semibold text-ink">
              {title}
            </h2>
            {subtitle && <div className="mt-0.5 text-small text-ink-muted">{subtitle}</div>}
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            className={cn(
              "inline-flex shrink-0 items-center gap-1.5 rounded-control px-2.5 py-1.5 text-small font-medium text-ink-muted",
              "hover:bg-surface-subtle hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500",
            )}
          >
            <X className="h-4 w-4" aria-hidden="true" />
            Close
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
      </div>
    </div>,
    document.body,
  );
}
