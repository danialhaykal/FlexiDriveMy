import { useId } from "react";
import type { InputHTMLAttributes } from "react";
import { cn } from "./cn";

// Labeled text input with an optional error state - for form controls
// like downpayment amount. The error message is wired to the input via
// aria-describedby/aria-invalid.
//
// Usage: <Input label="Downpayment (RM)" error={errors.downpayment}
//   value={downpayment} onChange={(e) => setDownpayment(e.target.value)} />

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  error?: string;
}

export function Input({ label, error, id, className, ...rest }: InputProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const errorId = `${inputId}-error`;

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={inputId} className="text-small font-medium text-ink">
        {label}
      </label>
      <input
        id={inputId}
        aria-invalid={Boolean(error) || undefined}
        aria-describedby={error ? errorId : undefined}
        className={cn(
          "rounded-control border bg-surface px-3 py-2 text-body text-ink",
          "focus:outline-none focus:ring-2 focus:ring-primary-500",
          error ? "border-danger-600" : "border-border",
          className,
        )}
        {...rest}
      />
      {error && (
        <p id={errorId} className="text-small text-danger-700">
          {error}
        </p>
      )}
    </div>
  );
}
