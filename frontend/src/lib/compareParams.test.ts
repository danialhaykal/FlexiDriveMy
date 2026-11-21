import { describe, expect, it } from "vitest";
import {
  DOWNPAYMENT_NOT_BELOW_PRICE_MESSAGE,
  downpaymentForVehicle,
  readCompareParams,
  writeCompareParams,
} from "./compareParams";

// Run 1 fix batch 5 (M4): the compare page's inputs in its query string.

describe("readCompareParams", () => {
  it("reads valid values", () => {
    expect(readCompareParams(new URLSearchParams("tenure=60&mileage=high&downpayment=26580.00"))).toEqual({
      tenureMonths: 60,
      mileageBand: "high",
      downpayment: "26580.00",
    });
  });

  it.each([
    "tenure=11&mileage=standard",
    "tenure=109",
    "tenure=36.5",
    "tenure=abc",
    "mileage=extreme",
    "downpayment=-5",
    "downpayment=1e5",
    "downpayment=26580.123",
    "",
  ])("ignores anything invalid (%s) instead of failing", (query) => {
    const parsed = readCompareParams(new URLSearchParams(query));

    expect(parsed.tenureMonths === null || (parsed.tenureMonths >= 12 && parsed.tenureMonths <= 108)).toBe(true);
    if (query.startsWith("tenure=1") || query.startsWith("tenure=a") || query.includes("36.5")) {
      expect(parsed.tenureMonths).toBeNull();
    }
    if (query.includes("extreme")) expect(parsed.mileageBand).toBeNull();
    if (query.startsWith("downpayment")) expect(parsed.downpayment).toBeNull();
  });
});

describe("downpaymentForVehicle", () => {
  it("keeps a link's downpayment that is usable for this car", () => {
    expect(downpaymentForVehicle("30000.00", "26580.00", "265800.00")).toBe("30000.00");
  });

  it.each<[string | null, string]>([
    [null, "no downpayment in the link"],
    ["1000.00", "below the 10% minimum"],
    ["265800.00", "the whole price"],
  ])("falls back to the minimum for %s (%s)", (fromUrl) => {
    expect(downpaymentForVehicle(fromUrl, "26580.00", "265800.00")).toBe("26580.00");
  });
});

describe("writeCompareParams", () => {
  it("writes the three inputs and keeps any other parameter", () => {
    const next = writeCompareParams(new URLSearchParams("ref=email"), {
      tenureMonths: 48,
      mileageBand: "standard",
      downpayment: "26580.00",
    });

    expect(next.toString()).toBe("ref=email&tenure=48&mileage=standard&downpayment=26580.00");
  });

  it("drops a blank downpayment rather than writing an empty value", () => {
    const next = writeCompareParams(new URLSearchParams("downpayment=1"), {
      tenureMonths: 48,
      mileageBand: "low",
      downpayment: " ",
    });

    expect(next.has("downpayment")).toBe(false);
  });
});

// Run 3 fix batch 5 (F-30c): the compare page says exactly what the API says.
describe("downpayment above the price", () => {
  it("uses the API's sentence word for word", () => {
    expect(DOWNPAYMENT_NOT_BELOW_PRICE_MESSAGE).toBe("Downpayment must be less than the vehicle's price.");
  });
});
