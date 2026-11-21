import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { VehicleCard } from "./VehicleCard";
import type { Vehicle } from "../../types/catalog";

function makeVehicle(overrides: Partial<Vehicle> = {}): Vehicle {
  return {
    id: 5,
    brand: 1,
    brand_name: "Toyota",
    name: "Alphard",
    trim: "2.4 Executive Lounge",
    body_segment: "mpv",
    model_year: 2026,
    msrp: "548000.00",
    min_downpayment: "54800.00",
    engine_capacity_kw: "201.53",
    powertrain: "petrol",
    engine_capacity_cc: 2393,
    spec_complete: true,
    thumbnail_url: "",
    is_active: true,
    ...overrides,
  };
}

function renderCard(vehicle: Vehicle) {
  return render(
    <MemoryRouter>
      <VehicleCard vehicle={vehicle} />
    </MemoryRouter>,
  );
}

describe("VehicleCard (audit batch 6, F7)", () => {
  it("shows a deliberate photo placeholder with an accessible label when there is no photo", () => {
    renderCard(makeVehicle());

    const placeholder = screen.getByRole("img", { name: "No photo available for Toyota Alphard" });
    // UI-2: a car icon, the body segment and "Photo coming soon" (was the brand's initial) -
    // still no logo and no stock photo.
    expect(placeholder).toHaveTextContent("MPV");
    expect(placeholder).toHaveTextContent("Photo coming soon");
    expect(screen.queryByText("No image")).not.toBeInTheDocument();
  });

  it("shows the real photo and no placeholder when the car has one", () => {
    renderCard(makeVehicle({ thumbnail_url: "https://example.test/alphard.jpg" }));

    const photo = screen.getByRole("img", { name: "Toyota Alphard" });
    expect(photo).toHaveAttribute("src", "https://example.test/alphard.jpg");
    expect(photo).toHaveAttribute("loading", "lazy");
    expect(screen.queryByRole("img", { name: /No photo available/ })).not.toBeInTheDocument();
  });

  it("shows the model year beside the brand when present", () => {
    renderCard(makeVehicle({ model_year: 2026 }));

    expect(screen.getByText("Toyota · 2026")).toBeInTheDocument();
  });

  it("leaves the year out, never guessing one, when the car has none", () => {
    renderCard(makeVehicle({ model_year: null }));

    expect(screen.getByText("Toyota")).toBeInTheDocument();
    expect(screen.queryByText(/·/)).not.toBeInTheDocument();
  });

  it("still shows the name, trim and price", () => {
    renderCard(makeVehicle());

    expect(screen.getByText("Alphard 2.4 Executive Lounge")).toBeInTheDocument();
    expect(screen.getByText("RM 548,000.00")).toBeInTheDocument();
  });

  // --- Run 1 fix batch 5 (A4): power and powertrain under the price ------------

  // UI-2: power, the powertrain phrase and the body segment are separate chips (they
  // were one "150 kW · mild hybrid" line).
  it("shows power, the server's powertrain phrase and the body segment as chips under the price", () => {
    renderCard(makeVehicle({ engine_capacity_kw: "150.00", powertrain: "mild_hybrid", powertrain_phrase: "mild hybrid" }));

    const chips = screen.getAllByRole("listitem").map((chip) => chip.textContent);
    expect(chips).toEqual(["150 kW", "mild hybrid", "MPV"]);
  });

  // FX-2 (item 7): power is shown in whole kW (was "261.1 kW"); the API value is unchanged.
  it("rounds the power to whole kW and shows only what it has", () => {
    renderCard(makeVehicle({ engine_capacity_kw: "261.10", powertrain_phrase: "" }));

    expect(screen.getAllByRole("listitem").map((chip) => chip.textContent)).toEqual(["261 kW", "MPV"]);
  });

  it("is one link to the car's page with a visible focus ring and a View car label", () => {
    renderCard(makeVehicle());

    const card = screen.getByTestId("vehicle-card");
    expect(card.tagName).toBe("A");
    expect(card).toHaveAttribute("href", "/catalog/5");
    expect(card).toHaveClass("focus-visible:ring-2");
    expect(card).toHaveTextContent("View car");
  });

  it("shows nothing at all when both are missing - never 'null'", () => {
    const { container } = renderCard(makeVehicle({ engine_capacity_kw: "", powertrain: "", powertrain_phrase: "" }));

    expect(container.textContent).not.toMatch(/kW|null|undefined/);
  });
});
