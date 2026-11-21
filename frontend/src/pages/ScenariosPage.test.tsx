import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ScenariosPage } from "./ScenariosPage";
import { deleteScenario, listScenarios } from "../api/scenarios";
import { fetchEntireCatalog } from "../api/catalog";
import { fetchMileageBands } from "../api/mileageBands";
import { resetMileageBandOptionsCache } from "../hooks/useMileageBandOptions";
import { API_MILEAGE_BANDS } from "../test/mileageBandsFixture";
import type { Scenario } from "../types/scenarios";
import type { Vehicle } from "../types/catalog";

vi.mock("../api/scenarios", () => ({
  listScenarios: vi.fn(),
  deleteScenario: vi.fn(),
}));
// Redesign UI-4: the car's photo comes from the catalog list, the band's label from the API.
vi.mock("../api/catalog", () => ({ fetchEntireCatalog: vi.fn() }));
vi.mock("../api/mileageBands", () => ({ fetchMileageBands: vi.fn() }));

const mockedListScenarios = vi.mocked(listScenarios);
const mockedDeleteScenario = vi.mocked(deleteScenario);
const mockedFetchEntireCatalog = vi.mocked(fetchEntireCatalog);

function makeScenario(overrides: Partial<Scenario> = {}): Scenario {
  return {
    id: 1,
    title: "Honda City comparison",
    vehicle: 1,
    vehicle_label: "Honda City V",
    payload: {
      tenureMonths: 36,
      mileageBand: "standard",
      downpayment: "40000.00",
      comparison: {} as never, // not exercised by these tests - only list metadata is rendered
      tco: null,
      scoring: null,
    },
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-02-15T00:00:00Z",
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <ScenariosPage />
    </MemoryRouter>,
  );
}

describe("ScenariosPage", () => {
  beforeEach(() => {
    mockedListScenarios.mockReset();
    mockedDeleteScenario.mockReset();
    mockedFetchEntireCatalog.mockReset();
    mockedFetchEntireCatalog.mockResolvedValue([]);
    vi.mocked(fetchMileageBands).mockResolvedValue(API_MILEAGE_BANDS);
    resetMileageBandOptionsCache();
  });

  it("renders saved scenarios from the list response", async () => {
    mockedListScenarios.mockResolvedValueOnce([
      makeScenario({ id: 1, title: "Honda City comparison", vehicle_label: "Honda City V" }),
      makeScenario({ id: 2, title: "Toyota Vios comparison", vehicle_label: "Toyota Vios G" }),
    ]);

    renderPage();

    expect(await screen.findByText("Honda City comparison")).toBeInTheDocument();
    expect(screen.getByText("Toyota Vios comparison")).toBeInTheDocument();
    expect(screen.getByText(/Toyota Vios G/)).toBeInTheDocument();
  });

  it("shows the empty state when there are no saved scenarios", async () => {
    mockedListScenarios.mockResolvedValueOnce([]);

    renderPage();

    expect(await screen.findByText("No saved comparisons yet")).toBeInTheDocument();
  });

  it("removes a scenario from the list after a confirmed delete", async () => {
    mockedListScenarios.mockResolvedValueOnce([
      makeScenario({ id: 1, title: "Honda City comparison" }),
    ]);
    mockedDeleteScenario.mockResolvedValueOnce(undefined);

    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Honda City comparison");

    // FX-1 (X5): the app's own dialog (was a window.confirm spy returning true).
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete" }));

    expect(await screen.findByText("No saved comparisons yet")).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(mockedDeleteScenario).toHaveBeenCalledWith(1);
  });

  // --- QA audit L16 ---------------------------------------------------------

  it("shows a per-row error on a failed delete without hiding the rest of the list", async () => {
    mockedListScenarios.mockResolvedValueOnce([
      makeScenario({ id: 1, title: "Honda City comparison" }),
      makeScenario({ id: 2, title: "Toyota Vios comparison", vehicle: 2, vehicle_label: "Toyota Vios V" }),
    ]);
    mockedDeleteScenario.mockRejectedValueOnce(new Error("network error"));

    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Honda City comparison");

    const deleteButtons = screen.getAllByRole("button", { name: "Delete" });
    await user.click(deleteButtons[0]);
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Delete" }));

    expect(await screen.findByText("Could not delete this comparison. Please try again.")).toBeInTheDocument();
    // Both rows are still visible - the whole list didn't get replaced
    // by a page-level error screen.
    expect(screen.getByText("Honda City comparison")).toBeInTheDocument();
    expect(screen.getByText("Toyota Vios comparison")).toBeInTheDocument();
  });

  it("does not delete when the user cancels the confirm dialog", async () => {
    mockedListScenarios.mockResolvedValueOnce([
      makeScenario({ id: 1, title: "Honda City comparison" }),
    ]);

    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Honda City comparison");

    await user.click(screen.getByRole("button", { name: "Delete" }));
    await user.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.getByText("Honda City comparison")).toBeInTheDocument();
    expect(mockedDeleteScenario).not.toHaveBeenCalled();
  });

  // FX-1 (X5): Escape answers NO, as the browser's confirm box did, and focus goes back to the row's Delete.
  it("Escape closes the dialog without deleting and returns focus to Delete", async () => {
    mockedListScenarios.mockResolvedValueOnce([makeScenario({ id: 1, title: "Honda City comparison" })]);

    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Honda City comparison");
    const rowDelete = screen.getByRole("button", { name: "Delete" });

    await user.click(rowDelete);
    expect(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(rowDelete).toHaveFocus();
    expect(mockedDeleteScenario).not.toHaveBeenCalled();
  });

  // --- Redesign UI-4 -----------------------------------------------------------------

  it("says how many are saved and shows each card's stored figures, band label and photo", async () => {
    mockedFetchEntireCatalog.mockResolvedValue([
      { id: 5, brand_name: "BMW", name: "3 Series", body_segment: "sedan", thumbnail_url: "https://upload.wikimedia.org/bmw.jpg" } as Vehicle,
    ]);
    mockedListScenarios.mockResolvedValueOnce([
      makeScenario({
        id: 11,
        title: "BMW plan",
        vehicle: 5,
        vehicle_label: "BMW 3 Series 320i Sport",
        updated_at: "2026-03-01T00:00:00Z",
        payload: {
          tenureMonths: 60,
          mileageBand: "high",
          downpayment: "26780.00",
          comparison: {
            hire_purchase: { monthly_instalment: "4545.18" },
            gfv_leasing: { monthly_instalment: "2994.68" },
            subscription: null,
            unavailable: { subscription: "Subscription plans run for 12, 24 or 36 months." },
          } as never,
          tco: null,
          scoring: null,
        },
      }),
      makeScenario({ id: 4, title: "Old snapshot", vehicle: 99, payload: { tenureMonths: 36 } as never }),
    ]);

    const { container } = renderPage();

    expect(await screen.findByRole("heading", { level: 1, name: "My comparisons" })).toBeInTheDocument();
    expect(screen.getByText("2 saved")).toBeInTheDocument();
    const bmw = screen.getByText("BMW plan").closest("li") as HTMLElement;
    // Redesign UI-5: the band's name only, never today's km range.
    expect(await within(bmw).findByText("60 months · High · Last updated 1 Mar 2026")).toBeInTheDocument();
    expect(within(bmw).queryByText(/km/)).not.toBeInTheDocument();
    expect(within(bmw).getByText("RM 4,545.18")).toBeInTheDocument();
    expect(within(bmw).getByText("RM 2,994.68")).toBeInTheDocument();
    expect(within(bmw).getAllByText("–")).toHaveLength(1);
    await vi.waitFor(() =>
      expect(container.querySelector("img")).toHaveAttribute("src", "https://upload.wikimedia.org/bmw.jpg"),
    );

    // An older snapshot: every missing figure is "–", the archived car gets the placeholder.
    const old = screen.getByText("Old snapshot").closest("li") as HTMLElement;
    expect(within(old).getAllByText("–")).toHaveLength(3);
    expect(within(old).getByRole("img", { name: "No photo available for Honda City V" })).toBeInTheDocument();
    expect(within(old).getByText(/^36 months · Last updated/)).toBeInTheDocument();
  });

  it("keeps Delete as a quiet red action with the same confirm wording", async () => {
    mockedListScenarios.mockResolvedValueOnce([makeScenario()]);
    const confirm = vi.spyOn(window, "confirm");
    const user = userEvent.setup();

    renderPage();
    await screen.findByText("Honda City comparison");
    const button = screen.getByRole("button", { name: "Delete" });
    expect(button).toHaveAttribute("data-variant", "danger-quiet");
    expect(screen.getByRole("link", { name: "Open" })).toHaveAttribute("href", "/scenarios/1");

    await user.click(button);

    // FX-1 (X5): the same words in the app's dialog (was asserted as the window.confirm text); the browser box is gone.
    const dialog = screen.getByRole("alertdialog");
    expect(within(dialog).getByText("Delete this saved comparison?")).toBeInTheDocument();
    expect(within(dialog).getByText("This cannot be undone.")).toBeInTheDocument();
    expect(confirm).not.toHaveBeenCalled();
    expect(mockedDeleteScenario).not.toHaveBeenCalled();
  });

  it("offers Browse cars when nothing is saved", async () => {
    mockedListScenarios.mockResolvedValueOnce([]);

    renderPage();

    expect(await screen.findByText("No saved comparisons yet")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Browse cars" })).toHaveAttribute("href", "/catalog");
    expect(mockedFetchEntireCatalog).not.toHaveBeenCalled();
  });

  it("says the list could not load (not the empty state) and 'Try again' loads it again", async () => {
    mockedListScenarios.mockRejectedValueOnce(new Error("Network Error")).mockResolvedValueOnce([makeScenario()]);
    const user = userEvent.setup();

    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load your saved comparisons. Please try again.");
    expect(screen.queryByText("No saved comparisons yet")).not.toBeInTheDocument();
    expect(screen.queryByText(/saved$/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("Honda City comparison")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(mockedListScenarios).toHaveBeenCalledTimes(2);
  });
});
