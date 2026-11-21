import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { ArenaPage, VEHICLES_LOAD_ERROR } from "./ArenaPage";
import { DashboardPage, RECENT_LOAD_ERROR } from "./DashboardPage";
import { useAuth } from "../context/AuthContext";
import { listScenarios } from "../api/scenarios";
import { fetchEntireCatalog } from "../api/catalog";
import { fetchArena } from "../api/comparisons";
import type { Vehicle } from "../types/catalog";

// Run 3 fix batch 5 (F-29): when the API cannot be reached, Compare Cars no
// longer shows an empty picker and the Dashboard no longer says "No saved
// comparisons yet" - both say plainly that the list could not load and offer
// "Try again", which loads it again.

vi.mock("../context/AuthContext", () => ({ useAuth: vi.fn() }));
vi.mock("../api/scenarios", () => ({ listScenarios: vi.fn() }));
vi.mock("../api/catalog", () => ({ fetchEntireCatalog: vi.fn() }));
vi.mock("../api/comparisons", () => ({ fetchArena: vi.fn() }));

const NETWORK_ERROR = Object.assign(new Error("Network Error"), { isAxiosError: true, code: "ERR_NETWORK" });

const vehicle: Vehicle = {
  id: 5, brand: 1, brand_name: "BMW", name: "3 Series", trim: "320i Sport", body_segment: "sedan", model_year: 2026,
  msrp: "267800.00", min_downpayment: "26780.00", engine_capacity_kw: "135.00", powertrain: "petrol",
  engine_capacity_cc: 1998, spec_complete: true, thumbnail_url: "", is_active: true,
} as Vehicle;

beforeEach(() => {
  vi.mocked(listScenarios).mockReset();
  vi.mocked(fetchEntireCatalog).mockReset();
  vi.mocked(fetchArena).mockReset();
  vi.mocked(useAuth).mockReturnValue({
    user: { id: 1, email: "buyer@example.com", first_name: "Aina", last_name: "", phone_number: "", role: "user", date_joined: "2026-01-01" },
    isAuthenticated: true, isLoading: false, error: null, login: vi.fn(), logout: vi.fn(), updateProfile: vi.fn(),
  });
});

describe("Dashboard when the API cannot be reached", () => {
  it("says the list could not load (not 'No saved comparisons yet') and retries", async () => {
    vi.mocked(listScenarios).mockRejectedValueOnce(NETWORK_ERROR).mockResolvedValueOnce([]);
    const user = userEvent.setup();
    render(<MemoryRouter><DashboardPage /></MemoryRouter>);

    expect(await screen.findByRole("alert")).toHaveTextContent(RECENT_LOAD_ERROR);
    expect(screen.queryByText("No saved comparisons yet")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("No saved comparisons yet")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(listScenarios).toHaveBeenCalledTimes(2);
  });
});

describe("Compare Cars when the API cannot be reached", () => {
  it("says the car list could not load (not an empty picker) and retries", async () => {
    vi.mocked(fetchEntireCatalog).mockRejectedValueOnce(NETWORK_ERROR).mockResolvedValueOnce([vehicle]);
    const user = userEvent.setup();
    render(<MemoryRouter><ArenaPage /></MemoryRouter>);

    expect(await screen.findByRole("alert")).toHaveTextContent(VEHICLES_LOAD_ERROR);
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("checkbox", { name: "BMW 3 Series 320i Sport" })).toBeInTheDocument();
    expect(fetchEntireCatalog).toHaveBeenCalledTimes(2);
  });

  it("uses plain sentences", () => {
    expect(RECENT_LOAD_ERROR).toBe("Could not load your saved comparisons. Please try again.");
    expect(VEHICLES_LOAD_ERROR).toBe("Could not load the list of cars. Please try again.");
  });
});
