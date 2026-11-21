import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ArenaTable, arenaCompareUrl } from "./ArenaTable";
import type { ArenaEntry, ArenaResult } from "../../types/arena";
import type { ComparisonResult } from "../../types/comparisons";
import type { Vehicle } from "../../types/catalog";

// Redesign UI-4: from md the Arena is a table with one column per car; below md
// it is one card per car (switched by a media query, so each figure is in the
// page once). "Best" comes only from the API's winners; a reason every car
// shares in a row is said once under the row's label.

const SUB_REASON = "Subscription plans run for 12, 24 or 36 months.";

function comparison(overrides: Partial<ComparisonResult> = {}): ComparisonResult {
  return {
    vehicle_id: 1,
    tenure_months: 48,
    mileage_band: "standard",
    downpayment: "57500.00",
    hire_purchase: { monthly_instalment: "6130.21" },
    gfv_leasing: { monthly_instalment: "3340.38" },
    subscription: null,
    unavailable: { subscription: SUB_REASON },
    ...overrides,
  } as ComparisonResult;
}

function entry(id: number, overrides: Partial<ArenaEntry> = {}): ArenaEntry {
  return {
    vehicle_id: id, ok: true, error: null, comparison: comparison({ vehicle_id: id }), tco_net: "245367.80",
    model_degraded: false, forecast_source: "ml_model", tco_unavailable_reason: null, status_label: "Available",
    ...overrides,
  };
}

const ARENA: ArenaResult = {
  results: [
    entry(5),
    entry(7, {
      comparison: comparison({ vehicle_id: 7, hire_purchase: { monthly_instalment: "13261.46" } as never }),
      tco_net: "430000.00",
      model_degraded: true,
      forecast_source: "estimated_curve_unsupported",
    }),
  ],
  winners: {
    cheapest_hp: { winner_id: 5, tied_with: [5] },
    cheapest_gfv: { winner_id: 5, tied_with: [5, 7] },
    cheapest_subscription: null,
    lowest_tco: { winner_id: 5, tied_with: [5] },
  },
};

const VEHICLES = {
  5: { id: 5, brand_name: "BMW", name: "3 Series", trim: "320i Sport", body_segment: "sedan", thumbnail_url: "https://upload.wikimedia.org/bmw.jpg" },
  7: { id: 7, brand_name: "Porsche", name: "Macan", trim: "Electric", body_segment: "suv", thumbnail_url: "" },
} as unknown as Record<number, Vehicle>;

const INPUTS = { tenureMonths: 48, mileageBand: "standard" as const, downpayment: "57500.00" };

function stubWidth(isWide: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: isWide,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
}

function renderArena() {
  return render(
    <MemoryRouter>
      <ArenaTable arena={ARENA} vehiclesById={VEHICLES} compareInputs={INPUTS} />
    </MemoryRouter>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ArenaTable layout (redesign UI-4)", () => {
  it("from md: one table, a column per car with its photo, linked name and status badge", () => {
    stubWidth(true);
    renderArena();

    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.queryByRole("article")).not.toBeInTheDocument();
    const headers = screen.getAllByRole("columnheader");
    expect(headers.map((th) => th.textContent?.includes("Available") ?? false)).toEqual([false, true, true]);
    expect(within(headers[1]).getByRole("link", { name: "BMW 3 Series 320i Sport" })).toHaveAttribute(
      "href",
      "/catalog/5/compare?tenure=48&mileage=standard&downpayment=57500.00",
    );
    expect(headers[1].querySelector("img")).toHaveAttribute("src", "https://upload.wikimedia.org/bmw.jpg");
    expect(within(headers[2]).getByRole("img", { name: "No photo available for Porsche Macan" })).toBeInTheDocument();
  });

  it("below md: one card per car with the four figures, their Best badges and reasons", () => {
    stubWidth(false);
    renderArena();

    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    const bmw = screen.getByRole("article", { name: "BMW 3 Series 320i Sport" });
    const macan = screen.getByRole("article", { name: "Porsche Macan Electric" });

    expect(within(bmw).getByRole("link", { name: "BMW 3 Series 320i Sport" })).toHaveAttribute(
      "href",
      "/catalog/5/compare?tenure=48&mileage=standard&downpayment=57500.00",
    );
    expect(within(bmw).getByText("Hire Purchase (monthly)")).toBeInTheDocument();
    expect(within(bmw).getByText("TCO (Hire Purchase, net, 60 months)")).toBeInTheDocument();
    expect(within(bmw).getAllByText("Best")).toHaveLength(2); // HP and TCO
    expect(within(bmw).getAllByText("Best (tied)")).toHaveLength(1);
    expect(within(macan).getAllByText("Best (tied)")).toHaveLength(1);
    expect(within(macan).queryByText("Best")).not.toBeInTheDocument();
    // In a card each car gives its own reason.
    expect(within(bmw).getByText(SUB_REASON)).toBeInTheDocument();
    expect(within(macan).getByText(SUB_REASON)).toBeInTheDocument();
    expect(
      within(macan).getByText("Estimated curve - sits out of the TCO race (no machine-learning forecast for this car)"),
    ).toBeVisible();
  });

  it("gives a winner the 'recommended' Best badge, from the API's winners only", () => {
    stubWidth(true);
    renderArena();

    const best = screen.getAllByText("Best");
    expect(best).toHaveLength(2); // HP and TCO: car 5
    for (const badge of best) expect(badge).toHaveAttribute("data-tone", "recommended");
    expect(screen.getAllByText("Best (tied)")).toHaveLength(2); // GFV: both cars, as the API says
    // cheapest_subscription is null: nobody wins that row.
    const subRow = screen.getByText("Subscription (monthly)").closest("tr") as HTMLElement;
    expect(within(subRow).queryByText(/^Best/)).not.toBeInTheDocument();
  });

  it("says a reason every car shares once, under the row label, and 'Not available' in each cell", () => {
    stubWidth(true);
    renderArena();

    const subRow = screen.getByText("Subscription (monthly)").closest("tr") as HTMLElement;
    expect(within(subRow).getAllByText(SUB_REASON)).toHaveLength(1);
    expect(within(subRow).getAllByText(SUB_REASON)[0].closest("td")).toBe(subRow.querySelector("td"));
    expect(within(subRow).getAllByText("Not available")).toHaveLength(2);
  });

  it("keeps the reason in each cell when the cars' reasons differ", () => {
    stubWidth(true);
    const other = "Subscription isn't offered for this car.";
    render(
      <MemoryRouter>
        <ArenaTable
          arena={{
            ...ARENA,
            results: [ARENA.results[0], entry(7, { comparison: comparison({ vehicle_id: 7, unavailable: { subscription: other } }) })],
          }}
          vehiclesById={VEHICLES}
          compareInputs={INPUTS}
        />
      </MemoryRouter>,
    );

    const subRow = screen.getByText("Subscription (monthly)").closest("tr") as HTMLElement;
    const cells = subRow.querySelectorAll("td");
    expect(within(cells[0] as HTMLElement).queryByText(SUB_REASON)).not.toBeInTheDocument();
    expect(within(cells[1] as HTMLElement).getByText(SUB_REASON)).toBeInTheDocument();
    expect(within(cells[2] as HTMLElement).getByText(other)).toBeInTheDocument();
  });

  it("builds each compare link from the inputs the arena was fetched with", () => {
    expect(arenaCompareUrl(66, { tenureMonths: 60, mileageBand: "very_high", downpayment: "100000" })).toBe(
      "/catalog/66/compare?tenure=60&mileage=very_high&downpayment=100000",
    );
  });
});
