import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";
import { ResaleExplanationCard } from "./ResaleExplanationCard";
import type { ResaleValueExplanation } from "../../types/depreciation";

// Run 3 fix batch 5 (F-03): the API now sends the explanation amounts as 2-dp
// strings like every other money field; a comparison saved before that holds
// numbers. The card must show exactly the same text for both.

const AS_STRINGS: ResaleValueExplanation = {
  base_value: "267800.00",
  contributions: {
    vehicle_age: "-108726.02",
    mileage: "-23405.48",
    brand_code: "0.00",
    engine_litres: "0.00",
    body_type: "-0.00",
    recond: "0.00",
  },
  predicted_value: "135668.50",
};

// The same figures as an older saved snapshot stored them (JSON numbers).
const AS_NUMBERS: ResaleValueExplanation = {
  base_value: 267800.0,
  contributions: { vehicle_age: -108726.02, mileage: -23405.48, brand_code: 0, engine_litres: 0, body_type: -0, recond: 0 },
  predicted_value: 135668.5,
};

function cardText(explanation: ResaleValueExplanation): string {
  const { container, unmount } = render(<ResaleExplanationCard explanation={explanation} />);
  const text = container.textContent ?? "";
  unmount();
  return text;
}

describe("ResaleExplanationCard with string and number amounts", () => {
  it("shows identical text for the 2-dp strings and an older snapshot's numbers", () => {
    expect(cardText(AS_STRINGS)).toBe(cardText(AS_NUMBERS));
  });

  it("reads the strings as the server sent them", () => {
    const text = cardText(AS_STRINGS);

    expect(text).toContain("New priceRM 267,800.00");
    expect(text).toContain("Age-RM 108,726.02");
    expect(text).toContain("Mileage-RM 23,405.48");
    expect(text).toContain("Predicted resale valueRM 135,668.50");
    // factors that read RM 0.00 (including "-0.00") are left out
    expect(text).not.toContain("Brand tier");
    expect(text).not.toContain("Body type");
  });

  it("shows a positive string amount with a plus sign", () => {
    const text = cardText({ ...AS_STRINGS, contributions: { ...AS_STRINGS.contributions, recond: "1200.00" } });

    expect(text).toContain("Recond import+RM 1,200.00");
  });

  it("skips an amount an older snapshot does not have", () => {
    const old = { ...AS_NUMBERS, contributions: { vehicle_age: -108726.02, mileage: -23405.48 } } as unknown as ResaleValueExplanation;

    expect(cardText(old)).toContain("Age-RM 108,726.02");
  });
});
