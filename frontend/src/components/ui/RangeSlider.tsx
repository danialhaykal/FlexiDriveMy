import { useId, useRef } from "react";
import type { ReactNode } from "react";
import { cn } from "./cn";
import { numeric } from "./tokens";

// Labeled range input with the current value shown alongside it - for
// tenure/mileage/downpayment sliders. `formatValue` is display
// formatting only (e.g. "36 months"); this component never computes a
// financial figure itself (Python is the only layer that performs
// monetary/financial arithmetic).
//
// Usage: <RangeSlider label="Tenure" value={tenure} min={12} max={108}
//   step={12} formatValue={(v) => `${v} months`} onChange={setTenure} />
//
// A slider whose answer doesn't exist yet (`value` null, or `isUnset`) is
// shown as UNRATED: a "Not yet rated" badge, a greyed track and NO number, so
// the screen never displays a figure the app isn't actually using. The first
// real interaction (drag, track click or arrow key) is what sets it.

interface RangeSliderProps {
  label: string;
  // null = not answered yet: no number is shown and nothing is sent.
  value: number | null;
  min: number;
  max: number;
  step?: number;
  onChange: (value: number) => void;
  formatValue?: (value: number) => string;
  id?: string;
  className?: string;
  // Back-compat: true marks a slider unrated even though `value` is a number
  // (the number is then hidden too).
  isUnset?: boolean;
  // FX-2 (item 4): labelled ticks at these values (the slider still moves in
  // `step`s between them) - layout only, no value is computed from them.
  marks?: number[];
  // FX-2 (item 4): one small line under the slider (e.g. the API's own
  // "not offered" reasons for the chosen value).
  hint?: ReactNode;
}

// Keys that actually move a native range input. Tab/Shift/etc. must NOT count
// as answering it.
const ADJUSTING_KEYS = new Set(["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End", "PageUp", "PageDown"]);

export function RangeSlider({
  label,
  value,
  min,
  max,
  step = 1,
  onChange,
  formatValue = (v) => String(v),
  id,
  className,
  isUnset = false,
  marks,
  hint,
}: RangeSliderProps) {
  const generatedId = useId();
  const sliderId = id ?? generatedId;
  const marksId = `${sliderId}-marks`;
  const hintId = `${sliderId}-hint`;
  const unrated = isUnset || value === null;
  // The native input needs some position even while unrated; it is never shown
  // as a number and is replaced by the user's real answer on first interaction.
  const position = value ?? Math.round((min + max) / 2);

  // A native <input type="range"> only fires change/input when its committed
  // value actually differs from what it already holds, so an unrated slider
  // whose first interaction ends exactly on its resting position would never
  // report an answer. Committing on pointerup, and on the keys that move the
  // slider, reads the DOM's own current value so every deliberate interaction
  // ends in a real onChange call.
  const commitCurrentValue = (event: { currentTarget: HTMLInputElement }) => {
    onChange(Number(event.currentTarget.value));
  };

  // Run 1 fix batch 5 (A10): a single click or tap on the slider's resting
  // position is a rating (3 on a 1-5 slider). Touch browsers often cancel the
  // pointer events on a range input, but `click` is reliable for mouse and
  // tap alike. Only a click that STARTED on the slider counts - clicking its
  // label also fires a click on the input, and must not rate it - and Tab
  // focus alone never rates it (Batch 6 F2).
  const pressedOnSlider = useRef(false);

  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <div className="flex items-baseline justify-between gap-2">
        <label htmlFor={sliderId} className="text-small font-medium text-ink">
          {label}
        </label>
        <span className="flex items-center gap-2">
          {unrated ? (
            <span className="whitespace-nowrap rounded-full border border-warning-300 bg-warning-50 px-2 py-0.5 text-caption font-medium text-warning-700">
              Not yet rated
            </span>
          ) : (
            <span className={cn("text-small font-semibold text-primary-700", numeric)}>
              {formatValue(position)}
            </span>
          )}
        </span>
      </div>
      <input
        id={sliderId}
        type="range"
        min={min}
        max={max}
        step={step}
        value={position}
        aria-valuetext={unrated ? "Not yet rated" : undefined}
        list={marks ? marksId : undefined}
        aria-describedby={hint ? hintId : undefined}
        onChange={(event) => onChange(Number(event.target.value))}
        onPointerDown={() => {
          pressedOnSlider.current = true;
        }}
        onPointerUp={commitCurrentValue}
        onClick={(event) => {
          if (!pressedOnSlider.current) return;
          pressedOnSlider.current = false;
          commitCurrentValue(event);
        }}
        onKeyUp={(event) => {
          if (ADJUSTING_KEYS.has(event.key)) commitCurrentValue(event);
        }}
        className={cn(
          "h-2 w-full cursor-pointer",
          unrated ? "opacity-50 accent-ink-muted" : "accent-primary-600",
        )}
      />
      {marks && (
        <>
          <datalist id={marksId}>
            {marks.map((mark) => (
              <option key={mark} value={mark} />
            ))}
          </datalist>
          {/* Each label sits over its tick: (mark - min) / (max - min) of the track. */}
          <div className="relative h-4" aria-hidden="true">
            {marks.map((mark) => {
              const at = ((mark - min) / (max - min)) * 100;
              return (
                <span
                  key={mark}
                  className={cn("absolute top-0 text-caption text-ink-muted", numeric)}
                  style={{ left: `${at}%`, transform: at === 0 ? "none" : at === 100 ? "translateX(-100%)" : "translateX(-50%)" }}
                >
                  {mark}
                </span>
              );
            })}
          </div>
        </>
      )}
      {hint && (
        <p id={hintId} className="text-caption text-ink-muted">
          {hint}
        </p>
      )}
    </div>
  );
}
