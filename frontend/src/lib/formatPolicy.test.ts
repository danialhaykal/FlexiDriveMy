import { describe, expect, it } from "vitest";
import { formatPlainAmount, formatRatioPercent, formatRatioPoints } from "./formatPolicy";

// Redesign UI-6a: the admin tables SHOW the API's 4-dp ratios in readable units.

describe("formatRatioPercent", () => {
  it("shows a ratio as a percentage to 2 dp", () => {
    expect(formatRatioPercent("0.7807")).toBe("78.07%");
    expect(formatRatioPercent("0.5179")).toBe("51.79%");
    expect(formatRatioPercent("0.4000")).toBe("40.00%");
  });

  it("leaves anything that is not a number as it is", () => {
    expect(formatRatioPercent("n/a")).toBe("n/a");
  });
});

describe("formatRatioPoints", () => {
  it("shows ratio points with their sign", () => {
    expect(formatRatioPoints("0.0600")).toBe("+6.00 pts");
    expect(formatRatioPoints("-0.0800")).toBe("-8.00 pts");
    expect(formatRatioPoints("-0.0300")).toBe("-3.00 pts");
    expect(formatRatioPoints("0.0000")).toBe("0.00 pts");
  });
});

describe("formatPlainAmount", () => {
  it("keeps 2 to 4 decimals", () => {
    expect(formatPlainAmount("0.5000")).toBe("0.50");
    expect(formatPlainAmount("0.2550")).toBe("0.255");
    expect(formatPlainAmount("1.80")).toBe("1.80");
  });
});
