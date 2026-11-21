import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { VehicleDetailPage } from "./VehicleDetailPage";
import { fetchVehicleDetail } from "../api/catalog";
import { fetchComparison } from "../api/comparisons";
import { fetchMileageBands } from "../api/mileageBands";
import { resetMileageBandOptionsCache } from "../hooks/useMileageBandOptions";
import { API_MILEAGE_BANDS } from "../test/mileageBandsFixture";
import type { ComparisonResult } from "../types/comparisons";
import type { Vehicle } from "../types/catalog";

vi.mock("../api/catalog", () => ({
  fetchVehicleDetail: vi.fn(),
}));
vi.mock("../api/comparisons", () => ({
  fetchComparison: vi.fn(),
}));
vi.mock("../api/mileageBands", () => ({
  fetchMileageBands: vi.fn(),
}));

const mockedFetchVehicleDetail = vi.mocked(fetchVehicleDetail);
const mockedFetchComparison = vi.mocked(fetchComparison);
const mockedFetchMileageBands = vi.mocked(fetchMileageBands);

// The comparison API's answer for the quick look (BMW 320i, 36 months, standard band,
// the API's minimum downpayment) - the page must show these strings, never recompute them.
function makeComparison(overrides: Partial<ComparisonResult> = {}): ComparisonResult {
  return {
    vehicle_id: 5,
    tenure_months: 36,
    mileage_band: "standard",
    downpayment: "26780.00",
    hire_purchase: { monthly_instalment: "7257.38", upfront_cash: "26780.00", total_contract_outlay: "288045.68", interest_rate_percent: "2.8000" },
    gfv_leasing: {
      monthly_instalment: "3404.78", upfront_cash: "26780.00", total_contract_outlay: "288045.68",
      balloon_payment: "138693.62", residual_value_ratio: "0.5179",
    },
    subscription: {
      monthly_instalment: "5605.50", upfront_cash: "11211.00", total_contract_outlay: "201798.00",
      net_cost_after_bundled_benefits: "4949.05", fee_source: "estimate",
    },
    unavailable: {},
    ...overrides,
  } as ComparisonResult;
}

function makeVehicle(overrides: Partial<Vehicle> = {}): Vehicle {
  return {
    id: 5,
    brand: 1,
    brand_name: "BMW",
    name: "3 Series",
    trim: "320i Sport",
    body_segment: "sedan",
    model_year: 2025,
    msrp: "265800.00",
    min_downpayment: "26780.00",
    engine_capacity_kw: "135.00",
    powertrain: "petrol",
    engine_capacity_cc: 1998,
    spec_complete: true,
    thumbnail_url: "",
    is_active: true,
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/catalog/5"]}>
      <Routes>
        <Route path="/catalog/:id" element={<VehicleDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function specValue(label: string): string | null {
  return screen.getByText(label).nextElementSibling?.textContent ?? null;
}

describe("VehicleDetailPage specs", () => {
  beforeEach(() => {
    mockedFetchVehicleDetail.mockReset();
    mockedFetchComparison.mockReset();
    mockedFetchComparison.mockResolvedValue(makeComparison());
    mockedFetchMileageBands.mockReset();
    mockedFetchMileageBands.mockResolvedValue(API_MILEAGE_BANDS);
    resetMileageBandOptionsCache();
  });

  it("shows power output, engine displacement in cc and the powertrain as separate rows", async () => {
    mockedFetchVehicleDetail.mockResolvedValueOnce(makeVehicle());

    renderPage();

    expect(await screen.findByText("Power output")).toBeInTheDocument();
    expect(specValue("Power output")).toBe("135 kW");
    expect(specValue("Engine")).toBe("1,998 cc");
    expect(specValue("Powertrain")).toBe("Petrol");
    // The old, misleading label is gone.
    expect(screen.queryByText("Engine capacity")).not.toBeInTheDocument();
  });

  it("shows 'Electric motor' for a battery electric vehicle", async () => {
    mockedFetchVehicleDetail.mockResolvedValueOnce(
      makeVehicle({ powertrain: "bev", engine_capacity_cc: null, engine_capacity_kw: "261.10" }),
    );

    renderPage();

    expect(await screen.findByText("Power output")).toBeInTheDocument();
    expect(specValue("Power output")).toBe("261 kW"); // FX-2 (item 7): whole kW (was "261.1 kW")
    expect(specValue("Engine")).toBe("Electric motor");
    expect(specValue("Powertrain")).toBe("Battery electric (BEV)");
  });

  // --- Audit batch 6 (F7) ---------------------------------------------------

  it("shows a deliberate, labelled photo placeholder instead of a bare 'No image'", async () => {
    mockedFetchVehicleDetail.mockResolvedValueOnce(makeVehicle());

    renderPage();

    const placeholder = await screen.findByRole("img", { name: "No photo available for BMW 3 Series" });
    expect(placeholder).toBeInTheDocument();
    // UI-2: the body segment and "Photo coming soon" (was the brand's initial)
    expect(placeholder).toHaveTextContent("Sedan");
    expect(placeholder).toHaveTextContent("Photo coming soon");
    expect(screen.queryByText("No image")).not.toBeInTheDocument();
  });

  it("uses the real photo, with no placeholder, when the car has one", async () => {
    mockedFetchVehicleDetail.mockResolvedValueOnce(makeVehicle({ thumbnail_url: "https://example.test/bmw.jpg" }));

    renderPage();

    expect(await screen.findByRole("img", { name: "BMW 3 Series" })).toHaveAttribute("src", "https://example.test/bmw.jpg");
    expect(screen.queryByRole("img", { name: /No photo available/ })).not.toBeInTheDocument();
  });

  it("shows the model year when the car has one, and leaves the row out (never guesses) when it doesn't", async () => {
    mockedFetchVehicleDetail.mockResolvedValueOnce(makeVehicle({ model_year: 2025 }));
    const { unmount } = renderPage();
    expect(await screen.findByText("Power output")).toBeInTheDocument();
    expect(specValue("Model year")).toBe("2025");
    unmount();

    mockedFetchVehicleDetail.mockResolvedValueOnce(makeVehicle({ model_year: null }));
    renderPage();
    expect(await screen.findByText("Power output")).toBeInTheDocument();
    expect(screen.queryByText("Model year")).not.toBeInTheDocument();
  });

  it("omits the engine and powertrain rows for a legacy row that has neither yet, rather than guessing", async () => {
    mockedFetchVehicleDetail.mockResolvedValueOnce(
      makeVehicle({ powertrain: "", engine_capacity_cc: null, spec_complete: false }),
    );

    renderPage();

    expect(await screen.findByText("Power output")).toBeInTheDocument();
    expect(screen.queryByText("Engine")).not.toBeInTheDocument();
    expect(screen.queryByText("Powertrain")).not.toBeInTheDocument();
  });
});

describe("VehicleDetailPage hero, photo credit and quick look", () => {
  beforeEach(() => {
    mockedFetchVehicleDetail.mockReset();
    mockedFetchComparison.mockReset();
    mockedFetchMileageBands.mockReset();
    mockedFetchMileageBands.mockResolvedValue(API_MILEAGE_BANDS);
    resetMileageBandOptionsCache();
  });

  it("shows the price and the API's minimum downpayment as figures, and keeps the compare button", async () => {
    mockedFetchVehicleDetail.mockResolvedValueOnce(makeVehicle());
    mockedFetchComparison.mockResolvedValue(makeComparison());

    renderPage();

    expect(await screen.findByRole("heading", { level: 1, name: "3 Series 320i Sport" })).toBeInTheDocument();
    expect(screen.getByText("RM 265,800.00")).toBeInTheDocument();
    expect(screen.getByText("Minimum downpayment").nextElementSibling).toHaveTextContent("RM 26,780.00");
    // FX-1 (X4): the button opens the comparison on the quick look's own inputs (it was "/catalog/5/compare", which then
    // opened at the profile's tenure while "Monthly at a glance" showed 36 months).
    expect(screen.getByRole("link", { name: "Compare Financing Options" })).toHaveAttribute(
      "href",
      "/catalog/5/compare?tenure=36&mileage=standard&downpayment=26780.00",
    );
  });

  it("the Compare Financing Options button and 'See the full comparison' open the same comparison", async () => {
    mockedFetchVehicleDetail.mockResolvedValueOnce(makeVehicle());
    mockedFetchComparison.mockResolvedValue(makeComparison());

    renderPage();

    const seeAll = await screen.findByRole("link", { name: /See the full comparison/ });
    expect(screen.getByRole("link", { name: "Compare Financing Options" })).toHaveAttribute("href", seeAll.getAttribute("href")!);
  });

  it("asks the comparison API for 36 months, the standard band and the API's minimum downpayment, and shows its three figures unchanged", async () => {
    mockedFetchVehicleDetail.mockResolvedValueOnce(makeVehicle());
    mockedFetchComparison.mockResolvedValue(makeComparison());

    renderPage();

    const section = await screen.findByRole("region", { name: "Monthly at a glance" });
    expect(await within(section).findByText("RM 7,257.38")).toBeInTheDocument();
    expect(within(section).getByText("RM 3,404.78")).toBeInTheDocument();
    expect(within(section).getByText("RM 5,605.50")).toBeInTheDocument();
    expect(mockedFetchComparison).toHaveBeenCalledWith({
      vehicle: 5, tenureMonths: 36, mileageBand: "standard", downpayment: "26780.00",
    });
    // The band wording comes from the band API, never typed here.
    expect(section).toHaveTextContent(API_MILEAGE_BANDS[1].label);
    expect(within(section).getByText("Estimate")).toBeInTheDocument();
    const link = within(section).getByRole("link", { name: "See the full comparison" });
    expect(link).toHaveAttribute("href", "/catalog/5/compare?tenure=36&mileage=standard&downpayment=26780.00");
  });

  it("shows 'Not available' and the API's own reason for a pathway the API marks unavailable", async () => {
    const reason = "GFV leasing isn't offered for 36 months - it is offered for 12 to 60 months in 12-month steps.";
    mockedFetchVehicleDetail.mockResolvedValueOnce(makeVehicle());
    mockedFetchComparison.mockResolvedValue(makeComparison({ gfv_leasing: null, unavailable: { gfv_leasing: reason } }));

    renderPage();

    const section = await screen.findByRole("region", { name: "Monthly at a glance" });
    expect(await within(section).findByText(reason)).toBeInTheDocument();
    expect(within(section).getByText("Not available")).toBeInTheDocument();
    expect(within(section).getByText("RM 7,257.38")).toBeInTheDocument();
  });

  it("shows 'Try again' when the quick look fails, keeps the specs, and retries", async () => {
    const user = userEvent.setup();
    mockedFetchVehicleDetail.mockResolvedValueOnce(makeVehicle());
    mockedFetchComparison.mockRejectedValueOnce(new Error("network")).mockResolvedValueOnce(makeComparison());

    renderPage();

    const retry = await screen.findByRole("button", { name: "Try again" });
    expect(specValue("Power output")).toBe("135 kW");
    expect(screen.getByRole("link", { name: "Compare Financing Options" })).toBeInTheDocument();

    await user.click(retry);
    expect(await screen.findByText("RM 7,257.38")).toBeInTheDocument();
    expect(mockedFetchComparison).toHaveBeenCalledTimes(2);
  });

  it("credits a Wikimedia Commons photo with a link to its file page, in a new tab", async () => {
    mockedFetchVehicleDetail.mockResolvedValueOnce(
      makeVehicle({
        thumbnail_url:
          "https://thumb.wikimedia.org/wikipedia/commons/thumb/2/2f/BMW_G20_LCI_320i_Alpine_White_%281%29.jpg/1280px-BMW_G20_LCI_320i_Alpine_White_%281%29.jpg",
      }),
    );
    mockedFetchComparison.mockResolvedValue(makeComparison());

    renderPage();

    const credit = await screen.findByRole("link", { name: "Wikimedia Commons" });
    expect(credit).toHaveAttribute("href", "https://commons.wikimedia.org/wiki/File:BMW_G20_LCI_320i_Alpine_White_(1).jpg");
    expect(credit).toHaveAttribute("target", "_blank");
    expect(credit).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("shows no credit for a photo hosted anywhere else", async () => {
    mockedFetchVehicleDetail.mockResolvedValueOnce(makeVehicle({ thumbnail_url: "https://example.test/bmw.jpg" }));
    mockedFetchComparison.mockResolvedValue(makeComparison());

    renderPage();

    expect(await screen.findByRole("img", { name: "BMW 3 Series" })).toBeInTheDocument();
    expect(screen.queryByText(/Wikimedia/)).not.toBeInTheDocument();
  });
});

// FX-2 (item 1, R4-P4-02): a server that can't be reached is not a missing car.
describe("VehicleDetailPage when the vehicle can't be loaded", () => {
  beforeEach(() => {
    mockedFetchVehicleDetail.mockReset();
    mockedFetchComparison.mockReset();
    mockedFetchComparison.mockResolvedValue(makeComparison());
  });

  it("a network failure says the server can't be reached, and Try again loads the car", async () => {
    mockedFetchVehicleDetail.mockRejectedValueOnce({ isAxiosError: true, message: "Network Error" }).mockResolvedValueOnce(makeVehicle());
    const user = userEvent.setup();

    renderPage();

    expect(await screen.findByText("We can't reach the server right now. Check your connection and try again.")).toBeInTheDocument();
    expect(screen.queryByText("This vehicle could not be found.")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("heading", { level: 1, name: "3 Series 320i Sport" })).toBeInTheDocument();
  });

  it("a 5xx is also 'can't reach the server'", async () => {
    mockedFetchVehicleDetail.mockRejectedValueOnce({ isAxiosError: true, response: { status: 502, data: "" } });

    renderPage();

    expect(await screen.findByText(/We can't reach the server right now/)).toBeInTheDocument();
  });

  it("only a real 404 says the vehicle could not be found, with no Try again", async () => {
    mockedFetchVehicleDetail.mockRejectedValueOnce({ isAxiosError: true, response: { status: 404, data: { detail: "Not found." } } });

    renderPage();

    expect(await screen.findByText("This vehicle could not be found.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });
});
