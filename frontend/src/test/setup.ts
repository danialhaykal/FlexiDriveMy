import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

afterEach(() => {
  cleanup();
});

// jsdom has no ResizeObserver, which Recharts' ResponsiveContainer needs
// to size its SVG - without this, chart tests would only ever see a
// width=0/height=0 container and no rendered series. Firing the callback
// synchronously with a fixed, reasonable size lets charts render in tests.
class ResizeObserverStub {
  private callback: ResizeObserverCallback;

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
  }

  observe(target: Element) {
    const entry = { target, contentRect: { width: 600, height: 300 } } as ResizeObserverEntry;
    this.callback([entry], this as unknown as ResizeObserver);
  }

  unobserve() {}
  disconnect() {}
}

globalThis.ResizeObserver = ResizeObserverStub as unknown as typeof ResizeObserver;

// jsdom doesn't implement the Blob URL registry (createObjectURL /
// revokeObjectURL) - stub it so components that trigger a file download
// (e.g. F008's PDF export) don't crash in tests.
if (!URL.createObjectURL) {
  URL.createObjectURL = (() => "blob:mock-url") as typeof URL.createObjectURL;
}
if (!URL.revokeObjectURL) {
  URL.revokeObjectURL = () => {};
}
