import { afterEach, describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { NegativeEquityChart, Y_AXIS_WIDTH } from "./NegativeEquityChart";
import { CHART_EXPORT_SELECTOR } from "../exports/ExportPdfButton";
import type { MonthlyForecastPoint } from "../../types/depreciation";

// Run 2 fix batch 3: the value axis is 80px wide (was 64), so "RM 280k" stays on one
// line on screen and in the PDF (the PDF captures this same <svg>). jsdom draws no
// tick text (it measures every label as zero wide), so this pins the width; the
// one-line labels were checked in a real browser. The size test next door checks the
// wider axis still leaves the PDF limits their 3x headroom.

function makeForecast(): MonthlyForecastPoint[] {
  return Array.from({ length: 61 }, (_, month) => ({
    month,
    predicted_resale_value: (280000 - month * 2000).toFixed(2),
    hp_outstanding_balance: (260000 * (1 - month / 60)).toFixed(2),
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

const originalResizeObserver = globalThis.ResizeObserver;

describe("NegativeEquityChart value axis", () => {
  afterEach(() => {
    globalThis.ResizeObserver = originalResizeObserver;
  });

  it("is 80px wide", () => {
    expect(Y_AXIS_WIDTH).toBe(80);
  });

  it("draws the value axis at that width", () => {
    setChartWidth(600);
    const { container } = render(
      <NegativeEquityChart monthlyForecast={makeForecast()} crossoverMonth={null} shortfallAmount={null} />,
    );
    const svg = container.querySelector(CHART_EXPORT_SELECTOR);
    expect(svg).not.toBeNull();

    const axisLine = svg!.querySelector(".recharts-yAxis .recharts-cartesian-axis-line");
    expect(axisLine).not.toBeNull();
    expect(Number(axisLine!.getAttribute("width"))).toBe(80);
  });
});
