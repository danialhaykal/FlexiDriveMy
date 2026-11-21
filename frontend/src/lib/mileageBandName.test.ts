import { describe, expect, it } from "vitest";
import { bandNameFromLabel, mileageBandName } from "./mileageBandName";
import { API_MILEAGE_BANDS } from "../test/mileageBandsFixture";
import { MILEAGE_BAND_OPTIONS } from "../types/comparisons";

// Redesign UI-5: a saved comparison shows its band's NAME only, never a km range.

describe("bandNameFromLabel", () => {
  it("keeps the text before the dash of the API's label", () => {
    expect(API_MILEAGE_BANDS.map((band) => bandNameFromLabel(band.label))).toEqual([
      "Low", "Standard", "High", "Very high",
    ]);
  });

  it("leaves a label with no dash as it is", () => {
    expect(bandNameFromLabel("Standard")).toBe("Standard");
    expect(bandNameFromLabel("Very high")).toBe("Very high");
  });

  it("accepts an en dash or a hyphen with spaces round it", () => {
    expect(bandNameFromLabel("High – something")).toBe("High");
    expect(bandNameFromLabel("High - something")).toBe("High");
  });
});

describe("mileageBandName", () => {
  it("maps a band key through the API's list", () => {
    expect(mileageBandName("standard", API_MILEAGE_BANDS)).toBe("Standard");
    expect(mileageBandName("very_high", API_MILEAGE_BANDS)).toBe("Very high");
  });

  it("works with the built-in list shown before the API answers", () => {
    expect(mileageBandName("high", MILEAGE_BAND_OPTIONS)).toBe("High");
  });

  it("title-cases a key the list doesn't have, and gives '' for no key", () => {
    expect(mileageBandName("extra_high", API_MILEAGE_BANDS)).toBe("Extra High");
    expect(mileageBandName(undefined, API_MILEAGE_BANDS)).toBe("");
    expect(mileageBandName("", API_MILEAGE_BANDS)).toBe("");
  });
});
