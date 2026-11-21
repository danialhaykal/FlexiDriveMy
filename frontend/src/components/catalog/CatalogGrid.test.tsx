import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { CatalogGrid } from "./CatalogGrid";
import { fetchCatalog, fetchCatalogBrands } from "../../api/catalog";
import type { Vehicle } from "../../types/catalog";

vi.mock("../../api/catalog", () => ({
  fetchCatalog: vi.fn(),
  fetchCatalogBrands: vi.fn(),
}));

const mockedFetchCatalog = vi.mocked(fetchCatalog);
const mockedFetchCatalogBrands = vi.mocked(fetchCatalogBrands);

function makeVehicle(overrides: Partial<Vehicle> = {}): Vehicle {
  return {
    id: 1,
    brand: 1,
    brand_name: "Honda",
    name: "City",
    trim: "V",
    body_segment: "sedan",
    model_year: 2025,
    msrp: "99999.99",
    min_downpayment: "10000.00",
    engine_capacity_kw: "90.00",
    powertrain: "petrol",
    engine_capacity_cc: 1498,
    spec_complete: true,
    thumbnail_url: "",
    is_active: true,
    ...overrides,
  };
}

function renderGrid() {
  return render(
    <MemoryRouter>
      <CatalogGrid />
    </MemoryRouter>,
  );
}

describe("CatalogGrid", () => {
  beforeEach(() => {
    mockedFetchCatalog.mockReset();
    mockedFetchCatalogBrands.mockReset();
    mockedFetchCatalogBrands.mockResolvedValue([
      { id: 1, name: "Honda", tier_code: "A", is_active: true },
      { id: 2, name: "Toyota", tier_code: "A", is_active: true },
    ]);
  });

  it("renders vehicles from the initial fetch", async () => {
    mockedFetchCatalog.mockResolvedValueOnce({
      count: 1,
      next: null,
      previous: null,
      results: [makeVehicle()],
    });

    renderGrid();

    expect(await screen.findByText("City V")).toBeInTheDocument();
    expect(mockedFetchCatalog).toHaveBeenCalledTimes(1);
  });

  it("updates the grid when a filter changes, without navigating away", async () => {
    mockedFetchCatalog.mockResolvedValueOnce({
      count: 1,
      next: null,
      previous: null,
      results: [makeVehicle({ id: 1, name: "City", brand_name: "Honda" })],
    });
    mockedFetchCatalog.mockResolvedValueOnce({
      count: 1,
      next: null,
      previous: null,
      results: [makeVehicle({ id: 2, name: "Vios", brand_name: "Toyota", brand: 2 })],
    });

    const user = userEvent.setup();
    const hrefBefore = window.location.href;

    renderGrid();
    expect(await screen.findByText("City V")).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText(/brand/i), "2");

    // The old result is gone and the newly-filtered one has taken its
    // place, in the same DOM tree - no page navigation occurred.
    await waitFor(() => expect(screen.queryByText("City V")).not.toBeInTheDocument());
    expect(await screen.findByText("Vios V")).toBeInTheDocument();

    expect(mockedFetchCatalog).toHaveBeenCalledTimes(2);
    expect(mockedFetchCatalog).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ brand: "2" }),
      1,
    );
    expect(window.location.href).toBe(hrefBefore);
  });

  it("shows the empty-state message when no vehicles match, and Reset All Filters restores the catalog", async () => {
    mockedFetchCatalog.mockResolvedValueOnce({
      count: 1,
      next: null,
      previous: null,
      results: [makeVehicle()],
    });
    mockedFetchCatalog.mockResolvedValueOnce({ count: 0, next: null, previous: null, results: [] });
    mockedFetchCatalog.mockResolvedValueOnce({
      count: 1,
      next: null,
      previous: null,
      results: [makeVehicle()],
    });

    const user = userEvent.setup();
    renderGrid();
    expect(await screen.findByText("City V")).toBeInTheDocument();

    const searchInput = screen.getByLabelText(/search/i);
    // A single change event (not per-keystroke) keeps the fetch call count
    // deterministic for this test.
    fireEvent.change(searchInput, { target: { value: "Bugatti" } });

    expect(
      await screen.findByText(
        "No vehicles match your selected criteria. Please broaden your filter parameters.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("City V")).not.toBeInTheDocument();

    const resetButton = screen.getByRole("button", { name: /reset all filters/i });
    await user.click(resetButton);

    expect(await screen.findByText("City V")).toBeInTheDocument();
    expect(searchInput).toHaveValue("");
    expect(mockedFetchCatalog).toHaveBeenCalledTimes(3);
  });

  // --- QA audit L4 ---------------------------------------------------------

  it("shows a specific message (not 'No vehicles match') when min price exceeds max price, and skips the request", async () => {
    mockedFetchCatalog.mockResolvedValueOnce({
      count: 1, next: null, previous: null, results: [makeVehicle()],
    });
    renderGrid();
    await screen.findByText("City V");
    mockedFetchCatalog.mockClear();

    fireEvent.change(screen.getByLabelText(/min price/i), { target: { value: "500000" } });
    fireEvent.change(screen.getByLabelText(/max price/i), { target: { value: "100000" } });

    expect(await screen.findByText("Min price can't exceed max price.")).toBeInTheDocument();
    expect(
      screen.queryByText("No vehicles match your selected criteria. Please broaden your filter parameters."),
    ).not.toBeInTheDocument();
    expect(mockedFetchCatalog).not.toHaveBeenCalled();
  });

  // --- QA audit M23 ---------------------------------------------------------

  it("renders Next/Previous page controls and fetches the next page", async () => {
    mockedFetchCatalog.mockResolvedValueOnce({
      count: 30,
      next: "http://testserver/api/vehicles/catalog/?page=2",
      previous: null,
      results: [makeVehicle({ id: 1, name: "City" })],
    });
    mockedFetchCatalog.mockResolvedValueOnce({
      count: 30,
      next: null,
      previous: "http://testserver/api/vehicles/catalog/?page=1",
      results: [makeVehicle({ id: 2, name: "Vios" })],
    });

    const user = userEvent.setup();
    renderGrid();
    expect(await screen.findByText("City V")).toBeInTheDocument();

    const previousButton = screen.getByRole("button", { name: "Previous" });
    const nextButton = screen.getByRole("button", { name: "Next" });
    expect(previousButton).toBeDisabled(); // page 1 - nothing before it
    expect(nextButton).not.toBeDisabled();

    await user.click(nextButton);

    expect(await screen.findByText("Vios V")).toBeInTheDocument();
    expect(mockedFetchCatalog).toHaveBeenLastCalledWith(expect.anything(), 2);
    expect(screen.getByText("Page 2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeDisabled(); // no further next page
  });

  it("resets to page 1 when a filter changes, rather than re-fetching the old page number first", async () => {
    mockedFetchCatalog.mockResolvedValue({
      count: 30,
      next: "http://testserver/api/vehicles/catalog/?page=2",
      previous: null,
      results: [makeVehicle({ id: 1, name: "City" })],
    });

    const user = userEvent.setup();
    renderGrid();
    expect(await screen.findByText("City V")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("Page 2");

    await user.selectOptions(screen.getByLabelText(/brand/i), "2");

    await screen.findByText("Page 1");
    // Every call for the new filter used page 1 - never page 2 first.
    for (const call of mockedFetchCatalog.mock.calls) {
      if ((call[0] as { brand: string }).brand === "2") {
        expect(call[1]).toBe(1);
      }
    }
  });

  // --- QA audit M7 ---------------------------------------------------------

  it("collapses rapid keystrokes in Min price into a single fetch, not one per keystroke", async () => {
    mockedFetchCatalog.mockResolvedValue({ count: 0, next: null, previous: null, results: [] });

    renderGrid();
    // Initial mount's debounced value equals the initial value immediately
    // (no artificial startup delay) - the first load fetch has already
    // fired by the time render() returns.
    expect(mockedFetchCatalog).toHaveBeenCalledTimes(1);

    vi.useFakeTimers();
    try {
      const minPriceInput = screen.getByLabelText(/min price/i);
      for (const value of ["1", "10", "100", "1000"]) {
        act(() => {
          fireEvent.change(minPriceInput, { target: { value } });
        });
      }

      // Still just the initial call - the debounce window hasn't elapsed.
      expect(mockedFetchCatalog).toHaveBeenCalledTimes(1);

      await act(async () => {
        vi.advanceTimersByTime(400);
      });

      expect(mockedFetchCatalog).toHaveBeenCalledTimes(2);
      expect(mockedFetchCatalog).toHaveBeenLastCalledWith(
      expect.objectContaining({ minPrice: "1000" }),
      1,
    );
    } finally {
      vi.useRealTimers();
    }
  });

  // --- UI-2: header, body-segment chips, filter count, retry --------------------------------

  it("titles the page Browse cars with the API's result count", async () => {
    mockedFetchCatalog.mockResolvedValueOnce({ count: 9, next: null, previous: null, results: [makeVehicle()] });

    renderGrid();

    expect(await screen.findByRole("heading", { level: 1, name: "Browse cars" })).toBeInTheDocument();
    expect(await screen.findByText("9 cars")).toBeInTheDocument();
  });

  it("filters by one body segment at a time with toggle chips, All first", async () => {
    const user = userEvent.setup();
    mockedFetchCatalog.mockResolvedValue({ count: 1, next: null, previous: null, results: [makeVehicle()] });

    renderGrid();
    await screen.findByText("City V");

    const group = screen.getByRole("group", { name: "Body segment" });
    const chips = Array.from(group.querySelectorAll("button"));
    expect(chips[0]).toHaveTextContent("All");
    expect(chips[0]).toHaveAttribute("aria-pressed", "true");

    await user.click(screen.getByRole("button", { name: "SUV" }));
    expect(screen.getByRole("button", { name: "SUV" })).toHaveAttribute("aria-pressed", "true");
    expect(chips[0]).toHaveAttribute("aria-pressed", "false");
    expect(group.querySelectorAll("[aria-pressed=true]")).toHaveLength(1);
    await waitFor(() =>
      expect(mockedFetchCatalog).toHaveBeenLastCalledWith(expect.objectContaining({ bodySegment: "suv" }), 1),
    );
  });

  it("says how many filters are on next to Reset All Filters, and nothing when none are", async () => {
    const user = userEvent.setup();
    mockedFetchCatalog.mockResolvedValue({ count: 1, next: null, previous: null, results: [makeVehicle()] });

    renderGrid();
    await screen.findByText("City V");
    expect(screen.queryByText(/filters? on$/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /reset all filters/i })).toBeDisabled();

    await user.selectOptions(screen.getByLabelText(/brand/i), "2");
    expect(screen.getByText("1 filter on")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Coupe" }));
    expect(screen.getByText("2 filters on")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /reset all filters/i }));
    expect(screen.queryByText(/filters? on$/)).not.toBeInTheDocument();
  });

  it("offers Try again after a failed load, and loads on retry", async () => {
    const user = userEvent.setup();
    mockedFetchCatalog
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce({ count: 1, next: null, previous: null, results: [makeVehicle()] });

    renderGrid();

    expect(await screen.findByText("Could not load the vehicle catalog. Please try again.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("City V")).toBeInTheDocument();
  });
});
