import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ArenaTable } from "./ArenaTable";
import type { ArenaEntry, ArenaResult } from "../../types/arena";

// Run 3 fix batch 4 (F-21): the Status row shows the server's own wording, and a car
// whose Hire Purchase is not offered shows "Not available" with the server's reason in
// the TCO row instead of a figure.

const REASON = "Your downpayment must be at least 10% of the vehicle price (RM 143,000.00).";

function entry(id: number, overrides: Partial<ArenaEntry> = {}): ArenaEntry {
  return {
    vehicle_id: id, ok: true, error: null, comparison: null, tco_net: "245367.80", model_degraded: false,
    forecast_source: "ml_model", tco_unavailable_reason: null, status_label: "Available", ...overrides,
  };
}

function arena(...results: ArenaEntry[]): ArenaResult {
  return {
    results,
    winners: { cheapest_hp: null, cheapest_gfv: null, cheapest_subscription: null, lowest_tco: null },
  };
}

describe("ArenaTable Status row", () => {
  it("shows the server's 'Not available at this downpayment' and the TCO reason as-is", () => {
    const below = entry(2, {
      tco_net: null, model_degraded: null, forecast_source: null, tco_unavailable_reason: REASON,
      status_label: "Not available at this downpayment",
    });

    render(<ArenaTable arena={arena(entry(1), below)} vehiclesById={{}} />);

    expect(screen.getByText("Not available at this downpayment")).toHaveAttribute("data-tone", "danger");
    expect(screen.getByText("Available")).toHaveAttribute("data-tone", "positive");
    expect(screen.getByText(REASON)).toBeInTheDocument();
    expect(screen.getByText("RM 245,367.80")).toBeInTheDocument(); // the other car's TCO is untouched
    expect(screen.queryByText(/Degraded/)).not.toBeInTheDocument();
  });

  it("shows 'Available' for an older response without status_label", () => {
    const old = entry(1);
    delete old.status_label;

    render(<ArenaTable arena={arena(old, entry(2))} vehiclesById={{}} />);

    expect(screen.getAllByText("Available")).toHaveLength(2);
  });

  it("keeps 'Unavailable' with the error for an error entry", () => {
    const failed = entry(2, {
      ok: false, error: "Downpayment must be less than the vehicle's price.", tco_net: null, model_degraded: null,
      forecast_source: null, status_label: null,
    });

    render(<ArenaTable arena={arena(entry(1), failed)} vehiclesById={{}} />);

    expect(screen.getByText("Unavailable")).toHaveAttribute("data-tone", "danger");
    expect(screen.getByText("Downpayment must be less than the vehicle's price.")).toBeInTheDocument();
  });
});
