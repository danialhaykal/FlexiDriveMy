import { afterEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useMediaQuery } from "./useMediaQuery";

// Redesign UI-4: the Arena switches between its table and its cards with this.

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useMediaQuery", () => {
  it("uses the fallback where the browser has no matchMedia (jsdom)", () => {
    expect(renderHook(() => useMediaQuery("(min-width: 768px)", true)).result.current).toBe(true);
    expect(renderHook(() => useMediaQuery("(min-width: 768px)", false)).result.current).toBe(false);
  });

  it("follows the query as it changes, and stops listening on unmount", () => {
    let listener: (() => void) | undefined;
    const list = {
      matches: false,
      addEventListener: vi.fn((_type: string, callback: () => void) => {
        listener = callback;
      }),
      removeEventListener: vi.fn(),
    };
    vi.stubGlobal("matchMedia", vi.fn(() => list));

    const { result, unmount } = renderHook(() => useMediaQuery("(min-width: 768px)", true));
    expect(result.current).toBe(false);

    list.matches = true;
    act(() => listener?.());
    expect(result.current).toBe(true);

    unmount();
    expect(list.removeEventListener).toHaveBeenCalledWith("change", listener);
  });
});
