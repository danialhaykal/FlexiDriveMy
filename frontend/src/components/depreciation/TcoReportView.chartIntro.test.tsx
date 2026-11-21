import { describe, expect, it } from "vitest";
import { chartIntro, FORECAST_HORIZON_MONTHS } from "./TcoReportView";

// Run 3 fix batch 5 (F-31): the chart stops at the 60-month forecast horizon, so
// above 60 months the caption says it covers the first 60 months of the term -
// word for word the PDF's sentence (backend comparison_rows.chart_intro).

describe("TCO chart caption", () => {
  it.each([12, 36, 60])("is unchanged for %i months", (tenure) => {
    expect(chartIntro({ tenure_months: tenure })).toBe(
      `Predicted resale value against the outstanding Hire Purchase balance over the ${tenure}-month term.`,
    );
  });

  it.each([72, 84, 108])("says the chart covers the first 60 months for %i months", (tenure) => {
    expect(chartIntro({ tenure_months: tenure })).toBe(
      "Predicted resale value against the outstanding Hire Purchase balance over the first 60 months of the " +
        `${tenure}-month term; the resale forecast does not go beyond 60 months.`,
    );
  });

  it("uses the server's 60-month horizon", () => {
    expect(FORECAST_HORIZON_MONTHS).toBe(60);
  });
});
