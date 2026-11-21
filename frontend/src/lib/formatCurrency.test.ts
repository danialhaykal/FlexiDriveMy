import { describe, expect, it } from "vitest";
import { formatCurrency, formatPercent, formatRatioAsPercent } from "./formatCurrency";

describe("formatCurrency", () => {
  it("formats a decimal string with the RM prefix, thousands separators, and 2 decimal places", () => {
    expect(formatCurrency("5344.44")).toBe("RM 5,344.44");
  });

  it("handles zero", () => {
    expect(formatCurrency("0.00")).toBe("RM 0.00");
  });

  it("handles a non-numeric string gracefully by returning it unchanged", () => {
    expect(formatCurrency("not-a-number")).toBe("not-a-number");
  });
});

describe("formatPercent", () => {
  it("formats an already percent-scaled value with a trailing %", () => {
    expect(formatPercent("3.0000")).toBe("3.00%");
  });

  it("handles a non-numeric string gracefully by returning it unchanged", () => {
    expect(formatPercent("nope")).toBe("nope");
  });
});

describe("formatRatioAsPercent", () => {
  it("scales a 0-1 ratio up to a percent", () => {
    expect(formatRatioAsPercent("0.5000")).toBe("50.00%");
  });

  it("handles a non-numeric string gracefully by returning it unchanged", () => {
    expect(formatRatioAsPercent("nope")).toBe("nope");
  });
});
