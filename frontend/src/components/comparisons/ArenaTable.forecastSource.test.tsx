import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ArenaTable } from "./ArenaTable";
import type { ArenaEntry, ArenaResult } from "../../types/arena";

// Run 2 fix batch 3 (A14, X1): the Arena's TCO row says why a car sits out of the
// race. A car the model doesn't cover (electric...) is on the estimated curve by
// design; "Degraded" stays for a model that isn't available and for responses that
// carry no forecast_source (an older one).

const ESTIMATED = "Estimated curve - sits out of the TCO race (no machine-learning forecast for this car)";
const DEGRADED = "Degraded - excluded from TCO race";

function entry(id: number, overrides: Partial<ArenaEntry> = {}): ArenaEntry {
  return {
    vehicle_id: id, ok: true, error: null, comparison: null, tco_net: "245367.80", model_degraded: false,
    forecast_source: "ml_model", tco_unavailable_reason: null, ...overrides,
  };
}

function arena(...results: ArenaEntry[]): ArenaResult {
  return {
    results,
    winners: { cheapest_hp: null, cheapest_gfv: null, cheapest_subscription: null, lowest_tco: null },
  };
}

describe("ArenaTable TCO row", () => {
  it("says 'Estimated curve ...' for a car the model doesn't cover", () => {
    render(
      <ArenaTable
        arena={arena(entry(1), entry(2, { model_degraded: true, forecast_source: "estimated_curve_unsupported" }))}
        vehiclesById={{}}
      />,
    );

    const note = screen.getByText(ESTIMATED);
    expect(note).toHaveAttribute("data-tone", "neutral");
    expect(screen.queryByText(DEGRADED)).not.toBeInTheDocument();
  });

  it("keeps 'Degraded - excluded from TCO race' for a model that isn't available", () => {
    render(
      <ArenaTable
        arena={arena(entry(1, { model_degraded: true, forecast_source: "model_unavailable" }), entry(2))}
        vehiclesById={{}}
      />,
    );

    expect(screen.getByText(DEGRADED)).toHaveAttribute("data-tone", "warning");
    expect(screen.queryByText(ESTIMATED)).not.toBeInTheDocument();
  });

  it("keeps the old text for a response without forecast_source", () => {
    const old = entry(1, { model_degraded: true });
    delete old.forecast_source;

    render(<ArenaTable arena={arena(old, entry(2))} vehiclesById={{}} />);

    expect(screen.getByText(DEGRADED)).toBeInTheDocument();
    expect(screen.queryByText(ESTIMATED)).not.toBeInTheDocument();
  });

  it("adds nothing for a car whose curve is the machine-learning forecast", () => {
    render(<ArenaTable arena={arena(entry(1), entry(2))} vehiclesById={{}} />);

    expect(screen.queryByText(DEGRADED)).not.toBeInTheDocument();
    expect(screen.queryByText(ESTIMATED)).not.toBeInTheDocument();
  });

  it("shows both notes side by side when one car is each kind", () => {
    render(
      <ArenaTable
        arena={arena(
          entry(1, { model_degraded: true, forecast_source: "model_unavailable" }),
          entry(2, { model_degraded: true, forecast_source: "estimated_curve_unsupported" }),
        )}
        vehiclesById={{}}
      />,
    );

    expect(screen.getByText(DEGRADED)).toBeInTheDocument();
    expect(screen.getByText(ESTIMATED)).toBeInTheDocument();
  });
});
