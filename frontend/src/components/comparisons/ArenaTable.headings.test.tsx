import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ArenaTable } from "./ArenaTable";
import type { ArenaResult } from "../../types/arena";
import type { Vehicle } from "../../types/catalog";

// Run 3 fix batch 5 (F-25): the shared header cell upper-cased its text, which
// re-cased car names ("320i" -> "320I"). The redesign (UI-1) writes every header
// in sentence case, so a car name and the "Pathway" label both keep their own case.

const arena: ArenaResult = {
  results: [
    { vehicle_id: 5, ok: true, error: null, comparison: null, tco_net: null, model_degraded: null, tco_unavailable_reason: null },
    { vehicle_id: 6, ok: true, error: null, comparison: null, tco_net: null, model_degraded: null, tco_unavailable_reason: null },
  ],
  winners: { cheapest_hp: null, cheapest_gfv: null, cheapest_subscription: null, lowest_tco: null },
};

const vehiclesById = {
  5: { brand_name: "BMW", name: "3 Series", trim: "320i Sport" },
  6: { brand_name: "Mercedes-Benz", name: "C-Class", trim: "C200 Avantgarde" },
} as unknown as Record<number, Vehicle>;

describe("ArenaTable column headings", () => {
  it("keeps each car name's own case", () => {
    render(<ArenaTable arena={arena} vehiclesById={vehiclesById} />);

    for (const name of ["BMW 3 Series 320i Sport", "Mercedes-Benz C-Class C200 Avantgarde"]) {
      const label = screen.getByText(name);
      expect(label).toHaveTextContent(name);
      expect(label.closest("th")).not.toHaveClass("uppercase");
    }
  });

  it("writes the Pathway label in sentence case", () => {
    render(<ArenaTable arena={arena} vehiclesById={vehiclesById} />);

    const pathway = screen.getByRole("columnheader", { name: "Pathway" });
    expect(pathway).toHaveTextContent(/^Pathway$/);
    expect(pathway).not.toHaveClass("uppercase");
  });
});
