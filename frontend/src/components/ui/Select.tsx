import { useId } from "react";
import type { SelectHTMLAttributes } from "react";
import { cn } from "./cn";
import { InfoExpander } from "./InfoExpander";

// Labeled native select - for form controls like mileage band. The error
// message is wired to the select via aria-describedby/aria-invalid.
//
// Usage: <Select label="Mileage band" value={mileageBand}
//   onChange={(e) => setMileageBand(e.target.value)}
//   options={[{ value: "low", label: "Low (< 10k km/yr)" }, ...]} />
//        <Select ... helpText="Check your last renewal notice." helpSummary="Where do I find this?" />

interface SelectOption {
  value: string;
  label: string;
}

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label: string;
  options: SelectOption[];
  error?: string;
  // A short muted line under the select, also read out with it.
  helpText?: string;
  // When given, the help text is folded into an InfoExpander with this summary
  // instead of shown as a line. It stays in the page and is still read out
  // with the select (aria-describedby points at it).
  helpSummary?: string;
}

export function Select({ label, options, error, helpText, helpSummary, id, className, ...rest }: SelectProps) {
  const generatedId = useId();
  const selectId = id ?? generatedId;
  const errorId = `${selectId}-error`;
  const helpId = `${selectId}-help`;
  const describedBy = [helpText ? helpId : null, error ? errorId : null].filter(Boolean).join(" ");

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={selectId} className="text-small font-medium text-ink">
        {label}
      </label>
      <select
        id={selectId}
        aria-invalid={Boolean(error) || undefined}
        aria-describedby={describedBy || undefined}
        className={cn(
          "rounded-control border bg-surface px-3 py-2 text-body text-ink",
          "focus:outline-none focus:ring-2 focus:ring-primary-500",
          error ? "border-danger-600" : "border-border",
          className,
        )}
        {...rest}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
      {helpText &&
        (helpSummary ? (
          <InfoExpander summary={helpSummary}>
            <span id={helpId}>{helpText}</span>
          </InfoExpander>
        ) : (
          <p id={helpId} className="text-caption text-ink-muted">
            {helpText}
          </p>
        ))}
      {error && (
        <p id={errorId} className="text-small text-danger-700">
          {error}
        </p>
      )}
    </div>
  );
}
