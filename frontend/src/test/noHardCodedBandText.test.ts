import { describe, expect, it } from "vitest";

// Run 3 fix batch 6: the mileage bands' km figures live in ONE backend definition
// (apps/policy/mileage.py, policy data) and reach the screens through the API.
// No frontend file - app or test - may write a band km figure, except the one test
// fixture that mirrors the API (src/test/mileageBandsFixture.ts) and this file.

const SOURCES = import.meta.glob<string>(["../**/*.ts", "../**/*.tsx", "../**/*.css"], {
  query: "?raw",
  import: "default",
  eager: true,
});
const ALLOWED = new Set(["./mileageBandsFixture.ts", "./noHardCodedBandText.test.ts"]);
// A km figure next to a km unit ("20,000 km", "15000 km/year", "30,000+ km"), or an old-style band label.
const BAND_KM_TEXT = [
  /\b\d{1,3}(?:,\d{3})+\+?\s*(?:km|kilomet)/i,
  /\b\d{4,6}\s*(?:km|kilomet)/i,
  // FX-3: not a figure in kW (an EV road-tax range such as "Above 1,010 kW" is power, not mileage).
  /\b(?:up to|above|under|over)\s+\d{1,3}(?:,\d{3})+\b(?!\s*kW)/i,
  /\b\d{1,3},\d{3}\s*[-–]\s*\d{1,3},\d{3}\b/,
];

describe("no hard-coded mileage-band text in the frontend", () => {
  it("reads the whole source tree", () => {
    expect(Object.keys(SOURCES).length).toBeGreaterThan(100);
    expect(Object.keys(SOURCES)).toContain("../pages/AdminPolicyPage.tsx");
  });

  it("finds no band km figure outside the one test fixture", () => {
    const offenders: string[] = [];
    for (const [file, text] of Object.entries(SOURCES)) {
      if (ALLOWED.has(file.replace(/^\.\.\/test\//, "./"))) continue;
      text.split("\n").forEach((line, index) => {
        if (BAND_KM_TEXT.some((pattern) => pattern.test(line))) {
          offenders.push(`${file}:${index + 1}: ${line.trim()}`);
        }
      });
    }

    expect(offenders).toEqual([]);
  });

  it("would catch an old-style label (the check itself works)", () => {
    for (const sample of ["Standard (up to 20,000 km/year)", "Very High (30,000+ km/year)", "10,000-19,999", "15000 km"]) {
      expect(BAND_KM_TEXT.some((pattern) => pattern.test(sample)), sample).toBe(true);
    }
    // FX-3: still catches a figure after "above", but not a power range in kW.
    expect(BAND_KM_TEXT.some((pattern) => pattern.test("above 25,000 a year"))).toBe(true);
    expect(BAND_KM_TEXT.some((pattern) => pattern.test("Above 910 kW to 1,010 kW"))).toBe(false);
    expect(BAND_KM_TEXT.some((pattern) => pattern.test("Above 1,010 kW"))).toBe(false);
  });
});
