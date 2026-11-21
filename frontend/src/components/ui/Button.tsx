import type { ButtonHTMLAttributes } from "react";
import { cn } from "./cn";

// Action control with 5 variants and a loading state. Prefer this over a
// bare <button> so colour/spacing/focus-ring stay consistent. `type`
// defaults to "button" but can be overridden (e.g. type="submit" in a form).
//
//   primary       the one solid action on a screen
//   secondary     white with a border
//   ghost         quiet, no border
//   danger        solid red - only for the confirm step of a destructive
//                 action (e.g. the YES in a confirm dialog)
//   danger-quiet  red text, transparent - row actions such as Archive or
//                 Delete (they still ask to confirm)
//
// Usage: <Button variant="danger-quiet" isLoading={isSubmitting}>Archive</Button>

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger" | "danger-quiet";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  isLoading?: boolean;
}

const VARIANT_CLASSES: Record<ButtonVariant, string> = {
  primary: "bg-primary-600 text-white hover:bg-primary-700 active:bg-primary-800",
  secondary: "bg-surface text-ink border border-border hover:bg-surface-subtle",
  ghost: "bg-transparent text-ink hover:bg-surface-subtle",
  danger: "bg-danger-600 text-white hover:bg-danger-700",
  "danger-quiet": "bg-transparent text-danger-700 hover:bg-danger-50",
};

export function Button({
  variant = "primary",
  isLoading = false,
  disabled,
  className,
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      type="button"
      data-variant={variant}
      disabled={disabled || isLoading}
      aria-busy={isLoading || undefined}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-control px-4 py-2",
        "text-small font-semibold transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2",
        "disabled:cursor-not-allowed disabled:opacity-60",
        VARIANT_CLASSES[variant],
        className,
      )}
      {...rest}
    >
      {isLoading && (
        <span
          className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"
          aria-hidden="true"
        />
      )}
      {children}
    </button>
  );
}
