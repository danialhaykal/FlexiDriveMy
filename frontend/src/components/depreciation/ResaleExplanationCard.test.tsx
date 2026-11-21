import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ResaleExplanationCard } from "./ResaleExplanationCard";
import type { ResaleValueExplanation } from "../../types/depreciation";

function labelsInOrder(container: HTMLElement): string[] {
  const wanted = ["New price", "Age", "Mileage", "Brand tier", "Engine size", "Body type", "Recond import", "Predicted resale value"];
  return Array.from(container.querySelectorAll("span"))
    .map((span) => span.textContent ?? "")
    .filter((text) => wanted.includes(text));
}

const IN_ORDER: ResaleValueExplanation = {
  base_value: 267800,
  contributions: {
    vehicle_age: -90000.5,
    mileage: -2000.25,
    brand_code: -300,
    engine_litres: 0,
    body_type: 0,
    recond: 0,
  },
  predicted_value: 175499.25,
};

describe("ResaleExplanationCard", () => {
  it("lists the factors in the fixed order and leaves out the ones that read RM 0.00", () => {
    const { container } = render(<ResaleExplanationCard explanation={IN_ORDER} />);

    expect(labelsInOrder(container)).toEqual(["New price", "Age", "Mileage", "Brand tier", "Predicted resale value"]);
    expect(screen.queryByText("Engine size")).not.toBeInTheDocument();
    expect(screen.queryByText("Body type")).not.toBeInTheDocument();
    expect(screen.queryByText("Recond import")).not.toBeInTheDocument();
  });

  it("keeps the same order when the figures arrive with their keys in another order (a saved snapshot)", () => {
    // How a JSON column hands them back: alphabetical, not the order the card is read in.
    const shuffled = {
      base_value: 267800,
      contributions: {
        body_type: -10,
        brand_code: -20,
        engine_litres: -30,
        mileage: -40,
        recond: -50,
        vehicle_age: -60,
      },
      predicted_value: 267590,
    } as ResaleValueExplanation;

    const { container } = render(<ResaleExplanationCard explanation={shuffled} />);

    expect(labelsInOrder(container)).toEqual([
      "New price",
      "Age",
      "Mileage",
      "Brand tier",
      "Engine size",
      "Body type",
      "Recond import",
      "Predicted resale value",
    ]);
  });

  it("hides a factor that only rounds to nothing in an older snapshot's unrounded figures", () => {
    const old = {
      ...IN_ORDER,
      contributions: { ...IN_ORDER.contributions, engine_litres: 0.004, body_type: -0.0049, recond: 0.0001 },
    };

    render(<ResaleExplanationCard explanation={old} />);

    expect(screen.queryByText("Engine size")).not.toBeInTheDocument();
    expect(screen.queryByText("Body type")).not.toBeInTheDocument();
    expect(screen.queryByText("Recond import")).not.toBeInTheDocument();
  });

  it("shows a small factor that does read as at least RM 0.01", () => {
    const small = { ...IN_ORDER, contributions: { ...IN_ORDER.contributions, engine_litres: 0.01 } };

    render(<ResaleExplanationCard explanation={small} />);

    expect(screen.getByText("Engine size")).toBeInTheDocument();
  });

  it("skips a factor an older snapshot doesn't have, without breaking", () => {
    const partial = {
      base_value: 100000,
      contributions: { vehicle_age: -5000, mileage: -1000 },
      predicted_value: 94000,
    } as unknown as ResaleValueExplanation;

    const { container } = render(<ResaleExplanationCard explanation={partial} />);

    expect(labelsInOrder(container)).toEqual(["New price", "Age", "Mileage", "Predicted resale value"]);
  });

  it("shows the amounts exactly as sent, with their sign", () => {
    render(<ResaleExplanationCard explanation={IN_ORDER} />);

    expect(screen.getByText("RM 267,800.00")).toBeInTheDocument();
    expect(screen.getByText("RM 175,499.25")).toBeInTheDocument();
    expect(screen.getByText(/^-RM 90,000\.50$/)).toBeInTheDocument();
  });
});
