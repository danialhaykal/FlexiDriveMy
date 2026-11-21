import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { VehicleReadinessPage } from "./VehicleReadinessPage";
import { fetchVehicleReadiness } from "../api/readiness";
import { fetchEntireCatalog } from "../api/catalog";
import type { ReadinessCheck, VehicleReadiness } from "../types/readiness";
import type { Vehicle } from "../types/catalog";

vi.mock("../api/readiness", () => ({ fetchVehicleReadiness: vi.fn() }));
// Redesign UI-6b: the car photos come from the catalog list.
vi.mock("../api/catalog", () => ({ fetchEntireCatalog: vi.fn() }));
const mockedFetch = vi.mocked(fetchVehicleReadiness);
const mockedCatalog = vi.mocked(fetchEntireCatalog);

function okChecks(): ReadinessCheck[] {
  return [
    { key: "specs", label: "Specs complete", status: "ok", detail: "Powertrain and engine details are filled in." },
    { key: "interest_rate", label: "Interest rate", status: "ok", detail: "BMW has a flat rate of 2.8000% a year." },
    { key: "model_year", label: "Model year", status: "warning", detail: "No model year recorded (recommended, not required)." },
  ];
}

const READY: VehicleReadiness = {
  vehicle_id: 5, label: "BMW 3 Series 320i Sport", brand_name: "BMW", status: "ready",
  missing_count: 0, warning_count: 1, checks: okChecks(),
};

const BROKEN: VehicleReadiness = {
  vehicle_id: 13, label: "Volvo XC90 Ultra T8", brand_name: "Volvo", status: "needs_attention",
  missing_count: 1, warning_count: 0,
  checks: [
    { key: "specs", label: "Specs complete", status: "ok", detail: "Powertrain and engine details are filled in." },
    {
      key: "interest_rate", label: "Interest rate", status: "missing",
      detail: "No active interest rate configured for brand 'Volvo'.",
    },
  ],
};

function renderPage() {
  return render(
    <MemoryRouter>
      <VehicleReadinessPage />
    </MemoryRouter>,
  );
}

describe("VehicleReadinessPage", () => {
  beforeEach(() => {
    mockedFetch.mockReset();
    mockedCatalog.mockReset();
    mockedCatalog.mockResolvedValue([]);
  });

  it("lists each car with a Ready or Needs attention badge and its counts", async () => {
    mockedFetch.mockResolvedValue([READY, BROKEN]);

    renderPage();

    const readyRow = (await screen.findByText("BMW 3 Series 320i Sport")).closest("tr")!;
    expect(within(readyRow).getByText("Ready")).toBeInTheDocument();
    const brokenRow = screen.getByText("Volvo XC90 Ultra T8").closest("tr")!;
    expect(within(brokenRow).getByText("Needs attention")).toBeInTheDocument();
    // missing count then recommended count, exactly as the API sent them
    expect(within(brokenRow).getAllByRole("cell").map((c) => c.textContent).slice(2, 4)).toEqual(["1", "0"]);
    expect(within(readyRow).getAllByRole("cell").map((c) => c.textContent).slice(2, 4)).toEqual(["0", "1"]);
  });

  it("expands a car to show every check, its status and the real detail", async () => {
    mockedFetch.mockResolvedValue([READY, BROKEN]);
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Volvo XC90 Ultra T8");

    expect(screen.queryByText("No active interest rate configured for brand 'Volvo'.")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show details for Volvo XC90 Ultra T8" }));

    expect(screen.getByText("No active interest rate configured for brand 'Volvo'.")).toBeInTheDocument();
    expect(screen.getByText("Missing")).toBeInTheDocument();
    expect(screen.getAllByText("OK").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "Hide details for Volvo XC90 Ultra T8" }));
    expect(screen.queryByText("No active interest rate configured for brand 'Volvo'.")).not.toBeInTheDocument();
  });

  it("marks recommended items as Recommended, never as Missing", async () => {
    mockedFetch.mockResolvedValue([READY]);
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("BMW 3 Series 320i Sport");

    await user.click(screen.getByRole("button", { name: "Show details for BMW 3 Series 320i Sport" }));

    expect(screen.getByText("Recommended", { selector: "span" })).toBeInTheDocument();
    expect(screen.queryByText("Missing")).not.toBeInTheDocument();
  });

  it("shows the resale-forecast line as a neutral Info item, never as Missing or Recommended", async () => {
    const electric: VehicleReadiness = {
      vehicle_id: 21, label: "Porsche Macan Electric Macan RWD", brand_name: "Porsche", status: "ready",
      missing_count: 0, warning_count: 0,
      checks: [
        { key: "specs", label: "Specs complete", status: "ok", detail: "Powertrain and engine details are filled in." },
        {
          key: "resale_forecast", label: "Resale forecast: estimated curve (electric car)", status: "info",
          detail: "The training data has no electric cars, so this car uses the estimated curve from planning assumptions.",
        },
      ],
    };
    mockedFetch.mockResolvedValue([electric]);
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("Porsche Macan Electric Macan RWD");

    // Ready stays Ready, and neither count moves, because of an informational line.
    const row = screen.getByText("Porsche Macan Electric Macan RWD").closest("tr")!;
    expect(within(row).getByText("Ready")).toBeInTheDocument();
    expect(within(row).getAllByRole("cell").map((c) => c.textContent).slice(2, 4)).toEqual(["0", "0"]);

    await user.click(screen.getByRole("button", { name: "Show details for Porsche Macan Electric Macan RWD" }));

    expect(screen.getByText("Resale forecast: estimated curve (electric car)")).toBeInTheDocument();
    expect(screen.getByText("Info", { selector: "span" })).toHaveAttribute("data-tone", "neutral");
    expect(screen.queryByText("Missing")).not.toBeInTheDocument();
    expect(screen.queryByText("Recommended")).not.toBeInTheDocument();
  });

  it("filters to the cars that need attention", async () => {
    mockedFetch.mockResolvedValue([READY, BROKEN]);
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("BMW 3 Series 320i Sport");

    await user.click(screen.getByLabelText("Needs attention only"));

    expect(screen.queryByText("BMW 3 Series 320i Sport")).not.toBeInTheDocument();
    expect(screen.getByText("Volvo XC90 Ultra T8")).toBeInTheDocument();

    await user.click(screen.getByLabelText("Needs attention only"));
    expect(screen.getByText("BMW 3 Series 320i Sport")).toBeInTheDocument();
  });

  it("says so when the filter leaves nothing, rather than showing an empty table", async () => {
    mockedFetch.mockResolvedValue([READY]);
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("BMW 3 Series 320i Sport");

    await user.click(screen.getByLabelText("Needs attention only"));

    expect(screen.getByText("Every car is ready")).toBeInTheDocument();
  });

  it("links each car to its edit form in Fleet Management", async () => {
    mockedFetch.mockResolvedValue([READY, BROKEN]);
    renderPage();

    const link = await screen.findByRole("link", { name: "Edit vehicle Volvo XC90 Ultra T8" });

    expect(link).toHaveAttribute("href", "/admin/fleet?edit=13");
  });

  // --- Audit batch 6b: not blank while the (slow) check runs ---------------------

  it("says it is checking, in a status region, until the table arrives", async () => {
    let finish!: (rows: VehicleReadiness[]) => void;
    mockedFetch.mockReturnValue(new Promise((resolve) => (finish = resolve)));

    renderPage();

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Checking every car - this can take a few seconds...");
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Needs attention only")).not.toBeInTheDocument();

    finish([READY, BROKEN]);

    expect(await screen.findByText("BMW 3 Series 320i Sport")).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.queryByText(/Checking every car/)).not.toBeInTheDocument();
  });

  it("shows the error message with a Retry button, and Retry reloads the report", async () => {
    mockedFetch.mockRejectedValueOnce(new Error("boom")).mockResolvedValueOnce([READY]);
    const user = userEvent.setup();

    renderPage();

    expect(await screen.findByText("Could not load vehicle readiness. Please try again.")).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("BMW 3 Series 320i Sport")).toBeInTheDocument();
    expect(screen.queryByText("Could not load vehicle readiness. Please try again.")).not.toBeInTheDocument();
    expect(mockedFetch).toHaveBeenCalledTimes(2);
  });

  it("shows the loading state again while a Retry is running", async () => {
    let finish!: (rows: VehicleReadiness[]) => void;
    mockedFetch.mockRejectedValueOnce(new Error("boom")).mockReturnValueOnce(new Promise((resolve) => (finish = resolve)));
    const user = userEvent.setup();

    renderPage();
    await user.click(await screen.findByRole("button", { name: "Retry" }));

    expect(screen.getByRole("status")).toHaveTextContent("Checking every car");
    finish([READY]);
    expect(await screen.findByText("BMW 3 Series 320i Sport")).toBeInTheDocument();
  });

  it("fetches the report once per visit: toggling the filter does not run the check again", async () => {
    mockedFetch.mockResolvedValue([READY, BROKEN]);
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("BMW 3 Series 320i Sport");

    await user.click(screen.getByLabelText("Needs attention only"));
    await user.click(screen.getByLabelText("Needs attention only"));
    await user.click(screen.getByRole("button", { name: "Show details for BMW 3 Series 320i Sport" }));

    expect(mockedFetch).toHaveBeenCalledTimes(1);
  });

  it("shows a plain message if readiness can't be loaded", async () => {
    mockedFetch.mockRejectedValue(new Error("boom"));

    renderPage();

    expect(await screen.findByText("Could not load vehicle readiness. Please try again.")).toBeInTheDocument();
  });

  it("uses no developer jargon", async () => {
    mockedFetch.mockResolvedValue([READY, BROKEN]);
    const { container } = renderPage();
    await screen.findByText("BMW 3 Series 320i Sport");

    expect(container.textContent).not.toMatch(/CLAUDE|\bUC0\d\d\b|\bF0\d\d\b|\bsprint\b|\bTODO\b|audit batch/i);
  });

  // --- Redesign UI-6b: header, tiles, toggle, photo ---------------------------------

  it("has the page header, the explanation one click away, and tiles counted from the rows", async () => {
    mockedFetch.mockResolvedValueOnce([READY, BROKEN, { ...READY, vehicle_id: 6, label: "Lexus ES 250 Luxury", warning_count: 2 }]);
    renderPage();

    expect(screen.getByRole("heading", { level: 1, name: "Vehicle readiness" })).toBeInTheDocument();
    expect(screen.getByText("Can the app fully price each car?")).toBeInTheDocument();
    expect(screen.getByText(/"Recommended" items never block pricing/).closest("details")).not.toBeNull();
    const summary = await screen.findByRole("region", { name: "Summary" });
    const tile = (label: string) => within(summary).getByText(label).nextElementSibling;
    expect(tile("Ready")).toHaveTextContent("2");
    expect(tile("Needs attention")).toHaveTextContent("1");
    expect(tile("Recommended items")).toHaveTextContent("3");
  });

  it("draws the 'Needs attention only' filter as a switch that still works as a checkbox", async () => {
    mockedFetch.mockResolvedValueOnce([READY, BROKEN]);
    const user = userEvent.setup();
    renderPage();
    await screen.findByText("BMW 3 Series 320i Sport");

    const toggle = screen.getByRole("switch", { name: "Needs attention only" });
    expect(toggle).not.toBeChecked();
    await user.click(toggle);
    expect(toggle).toBeChecked();
    expect(screen.queryByText("BMW 3 Series 320i Sport")).not.toBeInTheDocument();
  });

  it("shows each car's catalog photo, or the placeholder", async () => {
    mockedCatalog.mockResolvedValue([{ id: 5, thumbnail_url: "https://upload.wikimedia.org/bmw.jpg" } as Vehicle]);
    mockedFetch.mockResolvedValueOnce([READY, BROKEN]);
    renderPage();

    const bmwRow = (await screen.findByText("BMW 3 Series 320i Sport")).closest("tr") as HTMLElement;
    await vi.waitFor(() => expect(bmwRow.querySelector("img")).toHaveAttribute("src", "https://upload.wikimedia.org/bmw.jpg"));
    const volvoRow = screen.getByText("Volvo XC90 Ultra T8").closest("tr") as HTMLElement;
    expect(within(volvoRow).getByRole("img", { name: "No photo available for Volvo XC90 Ultra T8" })).toBeInTheDocument();
  });
});
