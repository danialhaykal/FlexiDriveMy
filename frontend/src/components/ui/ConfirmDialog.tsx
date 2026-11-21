import { useEffect, useRef } from "react";
import { Button } from "./Button";

// Batch 6A: a generic Yes/No confirmation modal - needed here for
// UC010's archive confirmation, deliberately generic (title/message/
// confirm-cancel labels, onConfirm/onCancel) rather than hardcoding
// "delete this vehicle?" copy into it, since a later batch (UC002's
// logout confirmation) reuses this same component for a different
// message entirely.
//
// Usage: <ConfirmDialog
//   isOpen={isConfirming}
//   title="Archive this vehicle?"
//   message="This can be undone later from the archived-records view."
//   confirmLabel="Archive"
//   onConfirm={handleArchive}
//   onCancel={() => setIsConfirming(false)}
// />

interface ConfirmDialogProps {
  isOpen: boolean;
  title: string;
  message: string;
  // Optional bullet list under the message (e.g. rows a reactivation skips).
  details?: string[];
  confirmLabel?: string;
  cancelLabel?: string;
  isConfirming?: boolean;
  // e.g. while the message's own content is still loading.
  isConfirmDisabled?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  isOpen,
  title,
  message,
  details = [],
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  isConfirming = false,
  isConfirmDisabled = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  // FX-1 (X5): behaves like the browser's own confirm box it replaces on My Comparisons - focus moves into the dialog
  // (to Cancel, the safe answer for a destructive action), Escape cancels (not while the action is running), and focus
  // goes back to whatever opened it. The latest onCancel / isConfirming are read through refs so these run once per open.
  const panelRef = useRef<HTMLDivElement>(null);
  const onCancelRef = useRef(onCancel);
  const isConfirmingRef = useRef(isConfirming);
  onCancelRef.current = onCancel;
  isConfirmingRef.current = isConfirming;

  useEffect(() => {
    if (!isOpen) return;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    panelRef.current?.querySelector<HTMLButtonElement>("button")?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !isConfirmingRef.current) {
        event.preventDefault();
        onCancelRef.current();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      if (opener && opener.isConnected) opener.focus();
    };
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div
      role="presentation"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onCancel}
    >
      <div
        ref={panelRef}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-message"
        className="w-full max-w-sm rounded-card border border-border bg-surface p-6 shadow-lg"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 id="confirm-dialog-title" className="text-h3 font-semibold text-ink">
          {title}
        </h2>
        <p id="confirm-dialog-message" className="mt-2 text-small text-ink-muted">
          {message}
        </p>
        {details.length > 0 && (
          <ul className="mt-2 list-disc pl-5 text-small text-ink-muted">
            {details.map((detail) => (
              <li key={detail}>{detail}</li>
            ))}
          </ul>
        )}
        <div className="mt-6 flex justify-end gap-2">
          <Button type="button" variant="ghost" onClick={onCancel} disabled={isConfirming}>
            {cancelLabel}
          </Button>
          <Button
            type="button"
            variant="danger"
            onClick={onConfirm}
            isLoading={isConfirming}
            disabled={isConfirmDisabled}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
