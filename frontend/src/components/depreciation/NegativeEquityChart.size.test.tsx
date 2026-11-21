import { afterEach, describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { NegativeEquityChart } from "./NegativeEquityChart";
import { CHART_EXPORT_SELECTOR } from "../exports/ExportPdfButton";
import type { MonthlyForecastPoint } from "../../types/depreciation";

// Run 1 fix batch 2 (G4): the PDF export refuses a chart_svg over
// MAX_CHART_SVG_BYTES (apps/exports/serializers.py) and drops one over
// MAX_CHART_SVG_ELEMENTS (apps/exports/svg_sanitizer.py). This measures the
// REAL chart, serialized exactly as ExportPdfButton captures it, at 12, 60
// and 108 months, and checks both limits leave at least 3x headroom over
// the largest. Measured in jsdom, which reports zero text widths, so
// Recharts draws every axis tick it can - the largest the chart gets.
const MAX_CHART_SVG_BYTES = 400_000; // keep in step with apps/exports/serializers.py
const MAX_CHART_SVG_ELEMENTS = 5_000; // keep in step with apps/exports/svg_sanitizer.py
const REQUIRED_HEADROOM = 3;

// A forecast shaped like the API's: one point per month 0..tenure, two-decimal
// strings of realistic magnitude (BMW 320i-like: RM 265,800 car, RM 239,220 financed).
function makeForecast(tenure: number): MonthlyForecastPoint[] {
  return Array.from({ length: tenure + 1 }, (_, month) => ({
    month,
    predicted_resale_value: (265800 - month * 1234.56789).toFixed(2),
    hp_outstanding_balance: (239220 * (1 - month / tenure)).toFixed(2),
  }));
}

function setChartWidth(width: number) {
  globalThis.ResizeObserver = class {
    private callback: ResizeObserverCallback;
    constructor(callback: ResizeObserverCallback) {
      this.callback = callback;
    }
    observe(target: Element) {
      this.callback([{ target, contentRect: { width, height: 320 } } as ResizeObserverEntry], this as never);
    }
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

function measure(tenure: number) {
  const { container, unmount } = render(
    <NegativeEquityChart monthlyForecast={makeForecast(tenure)} crossoverMonth={Math.floor(tenure / 3)} shortfallAmount="1000.00" />,
  );
  const svg = container.querySelector(CHART_EXPORT_SELECTOR);
  if (!svg) throw new Error("chart did not render");
  const markup = new XMLSerializer().serializeToString(svg);
  // The chart itself (both lines), not one of the legend's icon <svg>s.
  expect(markup.match(/recharts-line-curve/g)).toHaveLength(2);
  const result = {
    bytes: new TextEncoder().encode(markup).length,
    elements: svg.querySelectorAll("*").length + 1, // + the <svg> itself
  };
  unmount();
  return result;
}

const originalResizeObserver = globalThis.ResizeObserver;

describe("NegativeEquityChart export size", () => {
  afterEach(() => {
    globalThis.ResizeObserver = originalResizeObserver;
  });

  // 600px: the test setup's default. 1024px: the compare page's widest
  // content (max-w-5xl). 1600px: wider than the layout ever allows - a
  // deliberate overestimate, since a wider chart draws more axis ticks.
  it.each([600, 1024, 1600])("leaves at least 3x headroom under both PDF limits at %ipx wide", (width) => {
    setChartWidth(width);
    const sizes = [12, 60, 108].map((tenure) => ({ tenure, ...measure(tenure) }));
    console.info(`NegativeEquityChart at ${width}px: ${JSON.stringify(sizes)}`);

    // Tick thinning means the longest tenure isn't always the most
    // elements, so the check is against the largest of each measure.
    const maxBytes = Math.max(...sizes.map((size) => size.bytes));
    const maxElements = Math.max(...sizes.map((size) => size.elements));
    expect(maxBytes * REQUIRED_HEADROOM).toBeLessThanOrEqual(MAX_CHART_SVG_BYTES);
    expect(maxElements * REQUIRED_HEADROOM).toBeLessThanOrEqual(MAX_CHART_SVG_ELEMENTS);
  });
});
