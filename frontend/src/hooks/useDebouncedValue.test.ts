import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useDebouncedValue } from "./useDebouncedValue";

describe("useDebouncedValue", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("does not update until the delay has elapsed", () => {
    const { result, rerender } = renderHook(({ value }) => useDebouncedValue(value, 300), {
      initialProps: { value: "a" },
    });

    expect(result.current).toBe("a");

    rerender({ value: "ab" });
    expect(result.current).toBe("a");

    act(() => {
      vi.advanceTimersByTime(299);
    });
    expect(result.current).toBe("a");

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(result.current).toBe("ab");
  });

  it("collapses a rapid burst of changes into a single final value, not one update per keystroke", () => {
    const { result, rerender } = renderHook(({ value }) => useDebouncedValue(value, 300), {
      initialProps: { value: "" },
    });

    for (const value of ["m", "mi", "min", "min ", "min p"]) {
      rerender({ value });
      act(() => {
        vi.advanceTimersByTime(100); // well under the 300ms delay
      });
    }
    expect(result.current).toBe(""); // still nothing committed

    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(result.current).toBe("min p");
  });

  it("adopts a changed value immediately when resetKey changes, bypassing the delay", () => {
    // The ComparisonPage scenario this guards against: a vehicle loads,
    // its min_downpayment auto-fills the downpayment field - that
    // one-time programmatic fill must not sit behind the same 300ms
    // delay a real keystroke would, or the very first fetch on every
    // page load would be needlessly stalled.
    const { result, rerender } = renderHook(
      ({ value, resetKey }) => useDebouncedValue(value, 300, resetKey),
      { initialProps: { value: "", resetKey: undefined as number | undefined } },
    );
    expect(result.current).toBe("");

    rerender({ value: "40000.00", resetKey: 1 });
    expect(result.current).toBe("40000.00"); // no timer advance needed

    // A later, unrelated value change (same resetKey) still debounces normally.
    rerender({ value: "45000.00", resetKey: 1 });
    expect(result.current).toBe("40000.00");
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(result.current).toBe("45000.00");
  });
});
