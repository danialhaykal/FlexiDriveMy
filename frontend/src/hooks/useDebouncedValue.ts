import { useEffect, useState } from "react";

// QA audit M7: every keystroke in a text/number input that feeds a
// fetch effect was firing a real request per character - including a
// full ML inference call on every keystroke of a downpayment field.
// Debouncing the VALUE (not the input's own displayed state) means the
// input stays instantly responsive to typing, while the dependent fetch
// effect only sees a new value once the user pauses - never a fired-
// then-ignored request, since the fetch simply isn't triggered at all
// until the debounce settles.
//
// 350ms: a defensible middle ground - noticeably shorter than the
// ~500ms some debounce guidance uses for pure UI feedback (since this
// gates real network/ML calls, not just a visual re-render), but long
// enough to collect a normal multi-character typing burst (sub-150ms
// between keystrokes for most typists) into a single request.
export const DEBOUNCE_MS = 350;

export function useDebouncedValue<T>(value: T, delayMs: number = DEBOUNCE_MS, resetKey?: unknown): T {
  const [debounced, setDebounced] = useState(value);
  // `resetKey` is for a value that changes PROGRAMMATICALLY (e.g.
  // ComparisonPage auto-filling downpayment once a vehicle's details
  // load) rather than by the user typing - without it, that one-time
  // auto-fill would sit behind the same artificial delay as a real
  // keystroke, stalling the very first fetch on every page load.
  // Adjusted DURING RENDER (React's documented "storing information
  // from previous renders" pattern - calling setState mid-render lets
  // React restart the render with the new state before committing or
  // running effects, so the caller never sees one extra stale render),
  // not inside a useEffect - an effect-based reset would still let a
  // stale `debounced` value be read for one full render/commit first.
  const [previousResetKey, setPreviousResetKey] = useState(resetKey);
  const isResetting = resetKey !== undefined && resetKey !== previousResetKey;
  if (isResetting) {
    setPreviousResetKey(resetKey);
    setDebounced(value);
  }

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return isResetting ? value : debounced;
}
