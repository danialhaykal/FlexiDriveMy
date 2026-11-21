import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ArenaPage } from "./ArenaPage";
import { DEBOUNCE_MS } from "../hooks/useDebouncedValue";
import { DEFAULT_TENURE_MONTHS } from "../lib/defaults";
import { fetchEntireCatalog } from "../api/catalog";
import { fetchArena } from "../api/comparisons";
import type { Vehicle } from "../types/catalog";
import type { ArenaResult } from "../types/arena";

vi.mock("../api/catalog", () => ({
  fetchEntireCatalog: vi.fn(),
}));
vi.mock("../api/comparisons", () => ({
  fetchArena: vi.fn(),
}));

const mockedFetchEntireCatalog = vi.mocked(fetchEntireCatalog);
const mockedFetchArena = vi.mocked(fetchArena);

function makeVehicle(overrides: Partial<Vehicle> = {}): Vehicle {
  return {
    id: 1,
    brand: 1,
    brand_name: "Honda",
    name: "City",
    trim: "V",
    body_segment: "sedan",
    model_year: 2025,
    msrp: "80000.00",
    min_downpayment: "8000.00",
    engine_capacity_kw: "90.00",
    powertrain: "petrol",
    engine_capacity_cc: 1498,
    spec_complete: true,
    thumbnail_url: "",
    is_active: true,
    ...overrides,
  };
}

function makeArenaResult(overrides: Partial<ArenaResult> = {}): ArenaResult {
  return {
    results: [
      {
        vehicle_id: 1,
        ok: true,
        error: null,
        comparison: {
          vehicle_id: 1,
          tenure_months: 36,
          mileage_band: "standard",
          downpayment: "10000.00",
          hire_purchase: {
            monthly_instalment: "1591.67",
            upfront_cash: "10000.00",
            total_contract_outlay: "67300.12",
            interest_rate_percent: "2.5000",
          },
          gfv_leasing: {
            monthly_instalment: "988.89",
            upfront_cash: "10000.00",
            balloon_payment: "28000.00",
            total_contract_outlay: "45600.04",
            residual_value_ratio: "0.4000",
          },
          subscription: {
            monthly_instalment: "900.00",
            upfront_cash: "0.00",
            total_contract_outlay: "32400.00",
            net_cost_after_bundled_benefits: "650.00",
          },
          unavailable: {},
        },
        tco_net: "70000.00",
        model_degraded: false,
        tco_unavailable_reason: null,
      },
      {
        vehicle_id: 2,
        ok: true,
        error: null,
        comparison: {
          vehicle_id: 2,
          tenure_months: 36,
          mileage_band: "standard",
          downpayment: "10000.00",
          hire_purchase: {
            monthly_instalment: "2119.44",
            upfront_cash: "10000.00",
            total_contract_outlay: "86300.00",
            interest_rate_percent: "3.0000",
          },
          gfv_leasing: {
            monthly_instalment: "844.44",
            upfront_cash: "10000.00",
            balloon_payment: "48000.00",
            total_contract_outlay: "40399.84",
            residual_value_ratio: "0.6000",
          },
          subscription: {
            monthly_instalment: "700.00",
            upfront_cash: "0.00",
            total_contract_outlay: "25200.00",
            net_cost_after_bundled_benefits: "500.00",
          },
          unavailable: {},
        },
        tco_net: "65000.00",
        model_degraded: false,
        tco_unavailable_reason: null,
      },
    ],
    winners: {
      cheapest_hp: { winner_id: 1, tied_with: [1] },
      cheapest_gfv: { winner_id: 2, tied_with: [2] },
      cheapest_subscription: { winner_id: 2, tied_with: [2] },
      lowest_tco: { winner_id: 2, tied_with: [2] },
    },
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <ArenaPage />
    </MemoryRouter>,
  );
}

describe("ArenaPage", () => {
  beforeEach(() => {
    mockedFetchEntireCatalog.mockReset();
    mockedFetchArena.mockReset();
    mockedFetchEntireCatalog.mockResolvedValue([
      makeVehicle({ id: 1, name: "City" }),
      makeVehicle({ id: 2, name: "Vios", brand_name: "Toyota" }),
    ]);
  });

  it("renders the vehicle picker once vehicles load", async () => {
    renderPage();

    expect(await screen.findByText("Honda City V")).toBeInTheDocument();
    expect(screen.getByText("Toyota Vios V")).toBeInTheDocument();
  });

  it("prompts to select vehicles until at least 2 are chosen, and does not fetch", async () => {
    renderPage();
    await screen.findByText("Honda City V");

    expect(screen.getByText("Select at least 2 vehicles to compare.")).toBeInTheDocument();
    expect(mockedFetchArena).not.toHaveBeenCalled();

    const user = userEvent.setup();
    await user.click(screen.getByLabelText("Honda City V"));

    expect(screen.getByText("Select at least 2 vehicles to compare.")).toBeInTheDocument();
    expect(mockedFetchArena).not.toHaveBeenCalled();
  });

  it("fetches and renders the arena table once 2 vehicles are selected", async () => {
    mockedFetchArena.mockResolvedValueOnce(makeArenaResult());
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Honda City V");

    await user.click(screen.getByLabelText("Honda City V"));
    await user.click(screen.getByLabelText("Toyota Vios V"));

    expect(await screen.findByText("RM 1,591.67")).toBeInTheDocument(); // vehicle 1's HP
    expect(screen.getByText("RM 2,119.44")).toBeInTheDocument(); // vehicle 2's HP
    expect(mockedFetchArena).toHaveBeenCalledWith(expect.objectContaining({ vehicles: [1, 2] }));

    // Winner badges: vehicle 1 wins HP; vehicle 2 wins GFV/Subscription/TCO.
    expect(screen.getAllByText("Best")).toHaveLength(4);
  });

  it("fetches exactly once, with the auto-filled downpayment, however long the debounce takes to settle", async () => {
    // Regression: the auto-filled downpayment used to sit behind the
    // typing debounce, so a fast 2nd pick fetched with the stale value ("")
    // and then fetched AGAIN once the debounce settled - a timing-dependent
    // second call that, with mockResolvedValueOnce, made other tests here
    // flaky under load ("Cannot read properties of undefined (reading 'then')").
    mockedFetchArena.mockResolvedValue(makeArenaResult());
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Honda City V");
    await user.click(screen.getByLabelText("Honda City V"));
    await user.click(screen.getByLabelText("Toyota Vios V"));
    await screen.findByText("RM 1,591.67");
    // Wait out the whole debounce window: no late second request may follow.
    await new Promise((resolve) => setTimeout(resolve, DEBOUNCE_MS + 150));

    expect(mockedFetchArena).toHaveBeenCalledTimes(1);
    expect(mockedFetchArena).toHaveBeenCalledWith(
      expect.objectContaining({ vehicles: [1, 2], downpayment: "8000.00" }),
    );
  });

  // --- Audit batch 6 (F5): one default tenure, and the downpayment explained ---

  it("opens on the shared default tenure, the same one the single-car page uses", async () => {
    mockedFetchArena.mockResolvedValue(makeArenaResult());
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Honda City V");

    expect(DEFAULT_TENURE_MONTHS).toBe(48);
    expect(screen.getByText(`${DEFAULT_TENURE_MONTHS} months`)).toBeInTheDocument();
    await user.click(screen.getByLabelText("Honda City V"));
    await user.click(screen.getByLabelText("Toyota Vios V"));
    await screen.findByText("RM 1,591.67");
    expect(mockedFetchArena).toHaveBeenCalledWith(expect.objectContaining({ tenureMonths: DEFAULT_TENURE_MONTHS }));
  });

  it("explains the auto-filled downpayment while it still holds that value, naming the figure", async () => {
    mockedFetchEntireCatalog.mockResolvedValue([
      makeVehicle({ id: 1, name: "City", min_downpayment: "8000.00" }),
      makeVehicle({ id: 2, name: "Vios", brand_name: "Toyota", min_downpayment: "9500.00" }),
    ]);
    mockedFetchArena.mockResolvedValue(makeArenaResult());
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Honda City V");
    // nothing to explain before any car is selected
    expect(screen.queryByText(/Set to the highest minimum downpayment/)).not.toBeInTheDocument();
    await user.click(screen.getByLabelText("Honda City V"));
    await user.click(screen.getByLabelText("Toyota Vios V"));

    expect(
      await screen.findByText(
        "Set to the highest minimum downpayment among the selected cars (RM 9,500.00), so every car is comparable.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Downpayment (RM)")).toHaveValue(9500);
    expect(screen.queryByText("You set this manually.")).not.toBeInTheDocument();
  });

  it("says 'You set this manually' after an edit, and 'Reset to minimum' restores the auto value", async () => {
    mockedFetchEntireCatalog.mockResolvedValue([
      makeVehicle({ id: 1, name: "City", min_downpayment: "8000.00" }),
      makeVehicle({ id: 2, name: "Vios", brand_name: "Toyota", min_downpayment: "9500.00" }),
    ]);
    mockedFetchArena.mockResolvedValue(makeArenaResult());
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Honda City V");
    await user.click(screen.getByLabelText("Honda City V"));
    await user.click(screen.getByLabelText("Toyota Vios V"));
    await screen.findByText(/Set to the highest minimum downpayment/);

    await user.clear(screen.getByLabelText("Downpayment (RM)"));
    await user.type(screen.getByLabelText("Downpayment (RM)"), "20000");

    expect(screen.getByText(/You set this manually\./)).toBeInTheDocument();
    expect(screen.queryByText(/Set to the highest minimum downpayment/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Reset to minimum" }));

    expect(screen.getByLabelText("Downpayment (RM)")).toHaveValue(9500);
    expect(
      await screen.findByText(
        "Set to the highest minimum downpayment among the selected cars (RM 9,500.00), so every car is comparable.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/You set this manually\./)).not.toBeInTheDocument();
  });

  it("disables further selection past 3 vehicles", async () => {
    mockedFetchEntireCatalog.mockResolvedValue([
      makeVehicle({ id: 1, name: "City" }),
      makeVehicle({ id: 2, name: "Vios", brand_name: "Toyota" }),
      makeVehicle({ id: 3, name: "Civic" }),
      makeVehicle({ id: 4, name: "Almera", brand_name: "Nissan" }),
    ]);
    mockedFetchArena.mockResolvedValue(makeArenaResult());
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Honda City V");

    await user.click(screen.getByLabelText("Honda City V"));
    await user.click(screen.getByLabelText("Toyota Vios V"));
    await user.click(screen.getByLabelText("Honda Civic V"));

    expect(screen.getByLabelText("Nissan Almera V")).toBeDisabled();
  });

  it("shows a partial-failure vehicle's own error while the other still renders normally", async () => {
    const partial = makeArenaResult();
    mockedFetchArena.mockResolvedValueOnce({
      results: [
        partial.results[0],
        {
          vehicle_id: 2,
          ok: false,
          error: "No active subscription plan configured for 'Toyota Vios V'.",
          comparison: null,
          tco_net: null,
          model_degraded: null,
          tco_unavailable_reason: null,
        },
      ],
      winners: { cheapest_hp: null, cheapest_gfv: null, cheapest_subscription: null, lowest_tco: null },
    });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Honda City V");
    await user.click(screen.getByLabelText("Honda City V"));
    await user.click(screen.getByLabelText("Toyota Vios V"));

    expect(await screen.findByText("RM 1,591.67")).toBeInTheDocument(); // vehicle 1 still shows figures
    expect(
      screen.getByText("No active subscription plan configured for 'Toyota Vios V'."),
    ).toBeInTheDocument();
    expect(screen.getByText("Available")).toBeInTheDocument();
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
  });

  it("shows the loading skeleton while the arena request is in flight", async () => {
    mockedFetchArena.mockReturnValueOnce(new Promise(() => {})); // never resolves
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Honda City V");
    await user.click(screen.getByLabelText("Honda City V"));
    await user.click(screen.getByLabelText("Toyota Vios V"));

    expect(await screen.findAllByRole("status", { name: "Loading" })).not.toHaveLength(0);
  });

  it("shows the parsed vehicles-validation message verbatim on a 400 response", async () => {
    mockedFetchArena.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 400,
        data: { vehicles: ["Select between 2 and 3 vehicles to compare."] },
      },
    });
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Honda City V");
    await user.click(screen.getByLabelText("Honda City V"));
    await user.click(screen.getByLabelText("Toyota Vios V"));

    expect(await screen.findByText("Select between 2 and 3 vehicles to compare.")).toBeInTheDocument();
  });

  // --- Redesign UI-4 ----------------------------------------------------------------

  it("has the page header and picks cars from tiles that are real checkboxes", async () => {
    mockedFetchEntireCatalog.mockResolvedValue([
      makeVehicle({ id: 1, name: "City", thumbnail_url: "https://upload.wikimedia.org/city.jpg" }),
      makeVehicle({ id: 2, name: "Vios", brand_name: "Toyota" }),
    ]);
    mockedFetchArena.mockResolvedValue(makeArenaResult());
    const user = userEvent.setup();

    renderPage();

    expect(screen.getByRole("heading", { level: 1, name: "Compare cars" })).toBeInTheDocument();
    expect(
      screen.getByText("Pick 2 or 3 cars to see their monthly payments and total cost side by side."),
    ).toBeInTheDocument();
    const city = await screen.findByRole("checkbox", { name: "Honda City V" });
    const tile = city.closest("label") as HTMLElement;
    expect(tile.querySelector("img")).toHaveAttribute("src", "https://upload.wikimedia.org/city.jpg");
    expect(within(tile).getByText("RM 80,000.00")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "No photo available for Toyota Vios" })).toBeInTheDocument();
    expect(screen.getByText("0 of 3 selected")).toBeInTheDocument();

    // Space on the focused tile selects it, like any checkbox.
    city.focus();
    await user.keyboard(" ");
    expect(city).toBeChecked();
    expect(screen.getByText("1 of 3 selected")).toBeInTheDocument();
  });

  it("shows the empty state with its icon and the same wording until 2 cars are picked", async () => {
    renderPage();
    await screen.findByText("Honda City V");

    const message = screen.getByText("Select at least 2 vehicles to compare.");
    const box = message.parentElement as HTMLElement;
    expect(within(box).getByText("Select vehicles to compare")).toBeInTheDocument();
    expect(box.querySelector("svg")).not.toBeNull();
  });

  it("explains the auto-filled downpayment in one short line, the full sentence folded beside it", async () => {
    mockedFetchEntireCatalog.mockResolvedValue([
      makeVehicle({ id: 1, name: "City", min_downpayment: "8000.00" }),
      makeVehicle({ id: 2, name: "Vios", brand_name: "Toyota", min_downpayment: "9500.00" }),
    ]);
    mockedFetchArena.mockResolvedValue(makeArenaResult());
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Honda City V");
    await user.click(screen.getByLabelText("Honda City V"));
    await user.click(screen.getByLabelText("Toyota Vios V"));

    expect(await screen.findByText("Auto-filled with the highest minimum among the selected cars.")).toBeInTheDocument();
    const sentence = screen.getByText(
      "Set to the highest minimum downpayment among the selected cars (RM 9,500.00), so every car is comparable.",
    );
    expect(sentence.closest("details")?.querySelector("summary")).toHaveTextContent("Why this amount?");
  });

  it("links each car to its compare page on the inputs the arena used", async () => {
    mockedFetchArena.mockResolvedValue(makeArenaResult());
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Honda City V");
    await user.click(screen.getByLabelText("Honda City V"));
    await user.click(screen.getByLabelText("Toyota Vios V"));
    await screen.findByText("RM 1,591.67");

    expect(screen.getByRole("link", { name: "Honda City V" })).toHaveAttribute(
      "href",
      `/catalog/1/compare?tenure=${DEFAULT_TENURE_MONTHS}&mileage=standard&downpayment=8000.00`,
    );
  });
});
