import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { DashboardPage } from "./DashboardPage";
import { useAuth } from "../context/AuthContext";
import { listScenarios } from "../api/scenarios";
import { fetchEntireCatalog } from "../api/catalog";
import { fetchMileageBands } from "../api/mileageBands";
import { resetMileageBandOptionsCache } from "../hooks/useMileageBandOptions";
import { API_MILEAGE_BANDS } from "../test/mileageBandsFixture";
import type { Scenario } from "../types/scenarios";
import type { Vehicle } from "../types/catalog";

vi.mock("../context/AuthContext", () => ({
  useAuth: vi.fn(),
}));
vi.mock("../api/scenarios", () => ({
  listScenarios: vi.fn(),
}));
// Redesign UI-4: the car's photo comes from the catalog list, the band's label from the API.
vi.mock("../api/catalog", () => ({ fetchEntireCatalog: vi.fn() }));
vi.mock("../api/mileageBands", () => ({ fetchMileageBands: vi.fn() }));

const mockedUseAuth = vi.mocked(useAuth);
const mockedListScenarios = vi.mocked(listScenarios);
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
      comparison: {} as never, // not exercised by these tests
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
      <DashboardPage />
    </MemoryRouter>,
  );
}

describe("DashboardPage", () => {
  beforeEach(() => {
    mockedListScenarios.mockReset();
    mockedFetchEntireCatalog.mockReset();
    mockedFetchEntireCatalog.mockResolvedValue([]);
    vi.mocked(fetchMileageBands).mockResolvedValue(API_MILEAGE_BANDS);
    resetMileageBandOptionsCache();
    mockedUseAuth.mockReturnValue({
      user: {
        id: 1,
        email: "rider@example.com",
        first_name: "Alex",
        last_name: "Tan",
        phone_number: "",
        role: "user",
        date_joined: "2026-01-01",
      },
      isAuthenticated: true,
      isLoading: false,
      error: null,
      login: vi.fn(),
      logout: vi.fn(),
      updateProfile: vi.fn(),
    });
  });

  it("renders a welcome heading and the quick-action links", async () => {
    // A non-empty list here, deliberately - the empty state (tested
    // separately below) has its own "Browse Catalog" CTA with the same
    // accessible name, which would make this query ambiguous.
    mockedListScenarios.mockResolvedValueOnce([makeScenario()]);

    renderPage();

    // Redesign UI-4: "Welcome back", three quick-action tiles, and "See all" for the full list.
    expect(await screen.findByText("Welcome back, Alex")).toBeInTheDocument();
    const quickActions = screen.getByRole("navigation", { name: "Quick actions" });
    expect(within(quickActions).getByRole("link", { name: /browse cars/i })).toHaveAttribute("href", "/catalog");
    expect(within(quickActions).getByRole("link", { name: /compare cars/i })).toHaveAttribute("href", "/arena");
    expect(within(quickActions).getByRole("link", { name: /your financial profile/i })).toHaveAttribute(
      "href",
      "/profile/financial",
    );
    expect(screen.getByRole("link", { name: /see all/i })).toHaveAttribute("href", "/scenarios");
  });

  it("renders up to 5 most recent scenarios sorted by updated_at, each linking to its saved page", async () => {
    // Redesign UI-4: 5 rows (was 3), each with its own "Open" link; the newest is
    // also the "Pick up where you left off" card.
    mockedListScenarios.mockResolvedValueOnce([
      makeScenario({ id: 1, title: "Oldest", updated_at: "2026-01-01T00:00:00Z" }),
      makeScenario({ id: 2, title: "Second newest", updated_at: "2026-05-01T00:00:00Z" }),
      makeScenario({ id: 3, title: "Middle", updated_at: "2026-03-01T00:00:00Z" }),
      makeScenario({ id: 4, title: "Newest", updated_at: "2026-06-01T00:00:00Z" }),
      makeScenario({ id: 5, title: "Third", updated_at: "2026-04-01T00:00:00Z" }),
      makeScenario({ id: 6, title: "Fifth", updated_at: "2026-02-01T00:00:00Z" }),
    ]);

    renderPage();

    const recent = await screen.findByRole("region", { name: "Recent comparisons" });
    const rows = within(recent).getAllByRole("listitem");
    expect(rows.map((row) => row.querySelector("p")?.textContent)).toEqual([
      "Newest", "Second newest", "Third", "Middle", "Fifth",
    ]);
    expect(screen.queryByText("Oldest")).not.toBeInTheDocument();

    expect(within(recent).getByRole("link", { name: "Open Newest" })).toHaveAttribute("href", "/scenarios/4");
    expect(within(recent).getByRole("link", { name: "Open Fifth" })).toHaveAttribute("href", "/scenarios/6");
  });

  // --- Redesign UI-4: "Pick up where you left off" ---------------------------------

  it("shows the newest comparison's stored monthly figures, the band label from the API and an Open button", async () => {
    mockedListScenarios.mockResolvedValueOnce([
      makeScenario({ id: 1, title: "Older", updated_at: "2026-01-01T00:00:00Z" }),
      makeScenario({
        id: 11,
        title: "BMW plan",
        vehicle_label: "BMW 3 Series 320i Sport",
        updated_at: "2026-03-01T00:00:00Z",
        payload: {
          tenureMonths: 36,
          mileageBand: "standard",
          downpayment: "26780.00",
          comparison: {
            hire_purchase: { monthly_instalment: "7257.38" },
            gfv_leasing: { monthly_instalment: "3404.78" },
            subscription: null,
            unavailable: { subscription: "Subscription plans run for 12, 24 or 36 months." },
          } as never,
          tco: null,
          scoring: null,
        },
      }),
    ]);

    renderPage();

    const card = (await screen.findByText("Pick up where you left off")).closest("[data-tone='highlight']") as HTMLElement;
    expect(within(card).getByText("BMW plan")).toBeInTheDocument();
    // Redesign UI-5: the band's name only - never today's km range (a comparison saved
    // before the band change used other limits).
    expect(await within(card).findByText("36 months · Standard · Last updated 1 Mar 2026")).toBeInTheDocument();
    expect(within(card).queryByText(/km/)).not.toBeInTheDocument();
    expect(within(card).getByText("RM 7,257.38")).toBeInTheDocument();
    expect(within(card).getByText("RM 3,404.78")).toBeInTheDocument();
    // Subscription was not available when saved: "–", never a figure.
    expect(within(card).getByText("–")).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Open BMW plan" })).toHaveAttribute("href", "/scenarios/11");
  });

  it("shows '–' for every figure an older snapshot does not have", async () => {
    mockedListScenarios.mockResolvedValueOnce([
      makeScenario({ payload: { tenureMonths: 36, mileageBand: "standard", downpayment: "40000.00" } as never }),
    ]);

    renderPage();

    const card = (await screen.findByText("Pick up where you left off")).closest("[data-tone='highlight']") as HTMLElement;
    expect(within(card).getAllByText("–")).toHaveLength(3);
    expect(within(card).queryByText(/RM/)).not.toBeInTheDocument();
  });

  it("shows the car's photo from the catalog list", async () => {
    mockedFetchEntireCatalog.mockResolvedValue([
      { id: 5, brand_name: "BMW", name: "3 Series", body_segment: "sedan", thumbnail_url: "https://upload.wikimedia.org/bmw.jpg" } as Vehicle,
    ]);
    mockedListScenarios.mockResolvedValueOnce([makeScenario({ vehicle: 5 })]);

    const { container } = renderPage();

    await screen.findByText("Pick up where you left off");
    await vi.waitFor(() =>
      expect(container.querySelector("img")).toHaveAttribute("src", "https://upload.wikimedia.org/bmw.jpg"),
    );
  });

  it("uses the placeholder for a car that is no longer in the catalog", async () => {
    mockedListScenarios.mockResolvedValueOnce([makeScenario({ vehicle: 99, vehicle_label: "Archived Car X" })]);

    renderPage();

    expect(await screen.findByRole("img", { name: "No photo available for Archived Car X" })).toBeInTheDocument();
  });

  it("shows the empty state when there are no saved scenarios", async () => {
    mockedListScenarios.mockResolvedValueOnce([]);

    renderPage();

    expect(await screen.findByText("No saved comparisons yet")).toBeInTheDocument();
    // Redesign UI-4: the empty state's own "Browse cars" button, beside the quick-action tile.
    expect(screen.getAllByRole("link", { name: /browse cars/i })).toHaveLength(2);
    expect(screen.queryByText("Pick up where you left off")).not.toBeInTheDocument();
    expect(mockedFetchEntireCatalog).not.toHaveBeenCalled();
  });
});
