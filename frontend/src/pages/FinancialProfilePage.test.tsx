import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FinancialProfilePage } from "./FinancialProfilePage";
import { fetchFinancialProfile, saveFinancialProfile } from "../api/profile";
import { MILEAGE_BAND_OPTIONS } from "../types/comparisons";
import type { FinancialProfile } from "../types/profile";

vi.mock("../api/profile", () => ({
  fetchFinancialProfile: vi.fn(),
  saveFinancialProfile: vi.fn(),
}));

const mockedFetchFinancialProfile = vi.mocked(fetchFinancialProfile);
const mockedSaveFinancialProfile = vi.mocked(saveFinancialProfile);

function makeProfile(overrides: Partial<FinancialProfile> = {}): FinancialProfile {
  return {
    id: 1,
    monthly_budget: "2500.00",
    preferred_tenure_months: 60,
    annual_mileage_band: "high",
    ownership_preference: "retain",
    shariah_compliant_required: false,
    ncd_percent: "0.00",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("FinancialProfilePage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("renders an empty form when no profile has been saved yet", async () => {
    mockedFetchFinancialProfile.mockResolvedValueOnce(null);

    render(<FinancialProfilePage />);

    expect(await screen.findByRole("button", { name: "Save & Apply Baseline" })).toBeInTheDocument();
    expect(screen.getByLabelText("Monthly budget (RM)")).toHaveValue("");
    // The tenure slider shows the shared default (48 months) and that is exactly
    // what a save would send - never an unrated-looking value that is sent anyway.
    expect(screen.getByText("48 months")).toBeInTheDocument();
    expect(screen.queryByText("Not yet rated")).not.toBeInTheDocument();
  });

  it("prefills every field from the saved profile", async () => {
    mockedFetchFinancialProfile.mockResolvedValueOnce(makeProfile());

    render(<FinancialProfilePage />);

    expect(await screen.findByLabelText("Monthly budget (RM)")).toHaveValue("2500.00");
    expect(screen.getByText("60 months")).toBeInTheDocument();
    expect(screen.queryByText("Not yet rated")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Annual mileage band")).toHaveValue("high");
    expect(screen.getByLabelText("Ownership preference")).toHaveValue("retain");
    expect(screen.getByLabelText("I prefer Islamic financing (AITAB / profit rate)")).not.toBeChecked();
  });

  // --- Audit batch 6 (F6): one mileage-band list for the whole app ------------

  it("offers exactly the same mileage bands, in the same order and with the same labels, as the compare screens", async () => {
    mockedFetchFinancialProfile.mockResolvedValueOnce(null);

    render(<FinancialProfilePage />);
    await screen.findByRole("button", { name: "Save & Apply Baseline" });

    const select = screen.getByLabelText("Annual mileage band") as HTMLSelectElement;
    const offered = Array.from(select.options).filter((o) => o.value !== "");
    expect(offered.map((o) => [o.value, o.textContent])).toEqual(
      MILEAGE_BAND_OPTIONS.map((o) => [o.value, o.label]),
    );
    expect(offered.map((o) => o.value)).toEqual(["low", "standard", "high", "very_high"]);
    // Run 3 fix batch 6: until the API answers (not mocked here) the page shows the band
    // names alone - the km ranges only ever come from the API (see useMileageBandOptions.test).
    expect(offered.map((o) => o.textContent)).toEqual(["Low", "Standard", "High", "Very high"]);
  });

  it.each([
    ["10000", "standard"],
    ["20000", "high"],
    ["30000", "very_high"],
  ])("still loads a profile saved with the OLD value %s, showing the %s band", async (oldValue, band) => {
    mockedFetchFinancialProfile.mockResolvedValueOnce(makeProfile({ annual_mileage_band: oldValue as never }));

    render(<FinancialProfilePage />);

    expect(await screen.findByLabelText("Monthly budget (RM)")).toHaveValue("2500.00");
    expect(screen.getByLabelText("Annual mileage band")).toHaveValue(band);
  });

  it("copes with an unrecognised stored value by showing the standard band instead of breaking", async () => {
    mockedFetchFinancialProfile.mockResolvedValueOnce(makeProfile({ annual_mileage_band: "bogus" as never }));

    render(<FinancialProfilePage />);

    expect(await screen.findByLabelText("Monthly budget (RM)")).toHaveValue("2500.00");
    expect(screen.getByLabelText("Annual mileage band")).toHaveValue("standard");
  });

  it("describes the Islamic-financing preference honestly and never claims Shariah compliance", async () => {
    mockedFetchFinancialProfile.mockResolvedValueOnce(makeProfile());

    const { container } = render(<FinancialProfilePage />);
    const checkbox = await screen.findByLabelText("I prefer Islamic financing (AITAB / profit rate)");

    const help = screen.getByText(
      "Islamic hire purchase uses a profit rate instead of interest. This app does not yet price Islamic products separately, so figures are the conventional flat-rate estimates as an indicative guide only.",
    );
    expect(checkbox).toHaveAccessibleDescription(help.textContent ?? "");
    expect(container.textContent).not.toMatch(/Shariah-compliant/i);
    expect(container.textContent).not.toMatch(/required/i);
  });

  it("saves the form and shows a confirmation message", async () => {
    mockedFetchFinancialProfile.mockResolvedValueOnce(null);
    mockedSaveFinancialProfile.mockResolvedValueOnce(makeProfile({ monthly_budget: "3000.00" }));
    const user = userEvent.setup();

    render(<FinancialProfilePage />);
    await screen.findByRole("button", { name: "Save & Apply Baseline" });

    await user.type(screen.getByLabelText("Monthly budget (RM)"), "3000.00");
    await user.selectOptions(screen.getByLabelText("Annual mileage band"), "high");
    await user.selectOptions(screen.getByLabelText("Ownership preference"), "retain");
    await user.click(screen.getByRole("button", { name: "Save & Apply Baseline" }));

    expect(mockedSaveFinancialProfile).toHaveBeenCalledWith(
      expect.objectContaining({
        monthly_budget: "3000.00",
        annual_mileage_band: "high",
        ownership_preference: "retain",
      }),
    );
    expect(await screen.findByText("Baseline saved.")).toBeInTheDocument();
  });

  it("shows the server's exact verbatim message and preserves every other field on a 400", async () => {
    mockedFetchFinancialProfile.mockResolvedValueOnce(null);
    mockedSaveFinancialProfile.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 400,
        data: { monthly_budget: ["Please enter a valid positive numerical amount."] },
      },
    });
    const user = userEvent.setup();

    render(<FinancialProfilePage />);
    await screen.findByRole("button", { name: "Save & Apply Baseline" });

    await user.type(screen.getByLabelText("Monthly budget (RM)"), "-100.00");
    await user.selectOptions(screen.getByLabelText("Annual mileage band"), "very_high");
    await user.selectOptions(screen.getByLabelText("Ownership preference"), "upgrade");
    await user.click(screen.getByRole("button", { name: "Save & Apply Baseline" }));

    expect(
      await screen.findByText("Please enter a valid positive numerical amount."),
    ).toBeInTheDocument();
    // Every other already-entered value survives the failed submit.
    expect(screen.getByLabelText("Monthly budget (RM)")).toHaveValue("-100.00");
    expect(screen.getByLabelText("Annual mileage band")).toHaveValue("very_high");
    expect(screen.getByLabelText("Ownership preference")).toHaveValue("upgrade");
  });

  // --- Run 1 fix batch 3: No-Claim Discount ------------------------------------

  it("offers the six standard NCD steps with the help text, defaulting to 0%", async () => {
    mockedFetchFinancialProfile.mockResolvedValueOnce(null);

    render(<FinancialProfilePage />);
    await screen.findByRole("button", { name: "Save & Apply Baseline" });

    const select = screen.getByLabelText("No-Claim Discount (NCD) on your current car insurance") as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => [o.value, o.textContent])).toEqual([
      ["0.00", "0%"], ["25.00", "25%"], ["30.00", "30%"], ["38.33", "38.33%"], ["45.00", "45%"], ["55.00", "55%"],
    ]);
    expect(select).toHaveValue("0.00");
    expect(select).toHaveAccessibleDescription("Check your last insurance renewal notice. New drivers start at 0%.");
  });

  it("prefills the saved NCD and sends the chosen one", async () => {
    mockedFetchFinancialProfile.mockResolvedValueOnce(makeProfile({ ncd_percent: "38.33" }));
    mockedSaveFinancialProfile.mockResolvedValueOnce(makeProfile({ ncd_percent: "55.00" }));
    const user = userEvent.setup();

    render(<FinancialProfilePage />);
    const select = await screen.findByLabelText("No-Claim Discount (NCD) on your current car insurance");
    expect(select).toHaveValue("38.33");

    await user.selectOptions(select, "55.00");
    await user.click(screen.getByRole("button", { name: "Save & Apply Baseline" }));

    expect(mockedSaveFinancialProfile).toHaveBeenCalledWith(expect.objectContaining({ ncd_percent: "55.00" }));
    expect(await screen.findByText("Baseline saved.")).toBeInTheDocument();
    expect(select).toHaveValue("55.00");
  });

  it("toggles the Islamic-financing preference checkbox", async () => {
    mockedFetchFinancialProfile.mockResolvedValueOnce(null);
    mockedSaveFinancialProfile.mockResolvedValueOnce(makeProfile({ shariah_compliant_required: true }));
    const user = userEvent.setup();

    render(<FinancialProfilePage />);
    await screen.findByRole("button", { name: "Save & Apply Baseline" });

    await user.click(screen.getByLabelText("I prefer Islamic financing (AITAB / profit rate)"));
    await user.click(screen.getByRole("button", { name: "Save & Apply Baseline" }));

    expect(mockedSaveFinancialProfile).toHaveBeenCalledWith(
      expect.objectContaining({ shariah_compliant_required: true }),
    );
  });

  // --- Redesign UI-5: layout only - same fields, rules, messages and values ------------

  it("groups the fields under Budget, How you drive and Insurance and financing", async () => {
    mockedFetchFinancialProfile.mockResolvedValueOnce(makeProfile());

    render(<FinancialProfilePage />);

    expect(await screen.findByRole("heading", { level: 1, name: "Financial profile" })).toBeInTheDocument();
    expect(
      screen.getByText("These settings fill in your comparisons for you. You can still change them on any comparison."),
    ).toBeInTheDocument();
    const group = (title: string) => screen.getByRole("heading", { level: 2, name: title }).parentElement as HTMLElement;
    expect(within(group("Budget")).getByLabelText("Monthly budget (RM)")).toBeInTheDocument();
    expect(within(group("Budget")).getByLabelText("Monthly income (gross, RM)")).toBeInTheDocument();
    expect(within(group("Budget")).getByLabelText("Max DSR limit (%)")).toBeInTheDocument();
    expect(within(group("How you drive")).getByRole("slider", { name: "Preferred tenure" })).toBeInTheDocument();
    expect(within(group("How you drive")).getByLabelText("Annual mileage band")).toBeInTheDocument();
    expect(within(group("How you drive")).getByLabelText("Ownership preference")).toBeInTheDocument();
    expect(
      within(group("Insurance and financing")).getByLabelText("No-Claim Discount (NCD) on your current car insurance"),
    ).toBeInTheDocument();
    expect(
      within(group("Insurance and financing")).getByLabelText("I prefer Islamic financing (AITAB / profit rate)"),
    ).toBeInTheDocument();
  });

  it("folds the longer help into expanders but keeps the Islamic financing note visible", async () => {
    mockedFetchFinancialProfile.mockResolvedValueOnce(makeProfile());

    render(<FinancialProfilePage />);

    const income = await screen.findByText(
      "Used to start the AI Recommendation and Affordability tabs; you can change them for any comparison. Income is optional.",
    );
    expect(income.closest("details")?.querySelector("summary")).toHaveTextContent("What is this used for?");
    const ncd = screen.getByText("Check your last insurance renewal notice. New drivers start at 0%.");
    expect(ncd.closest("details")?.querySelector("summary")).toHaveTextContent("Where do I find this?");
    const islamic = screen.getByText(/This app does not yet price Islamic products separately/);
    expect(islamic.closest("details")).toBeNull();
  });

  it("has one save bar at the bottom of the form, sticky, with the saved message in it", async () => {
    mockedFetchFinancialProfile.mockResolvedValueOnce(makeProfile());
    mockedSaveFinancialProfile.mockResolvedValueOnce(makeProfile());
    const user = userEvent.setup();

    render(<FinancialProfilePage />);

    const button = await screen.findByRole("button", { name: "Save & Apply Baseline" });
    expect(screen.getAllByRole("button", { name: "Save & Apply Baseline" })).toHaveLength(1);
    const bar = button.parentElement as HTMLElement;
    expect(bar).toHaveClass("sticky", "bottom-0");
    expect(bar.parentElement?.tagName).toBe("FORM");
    expect(bar.parentElement?.lastElementChild).toBe(bar);

    await user.click(button);

    expect(within(bar).getByRole("status")).toHaveTextContent("Baseline saved.");
  });

  it("says the profile could not load and 'Try again' loads it again", async () => {
    mockedFetchFinancialProfile.mockRejectedValueOnce(new Error("Network Error")).mockResolvedValueOnce(makeProfile());
    const user = userEvent.setup();

    render(<FinancialProfilePage />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Could not load your saved financial profile. Please try again.",
    );
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByLabelText("Monthly budget (RM)")).toHaveValue("2500.00");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(mockedFetchFinancialProfile).toHaveBeenCalledTimes(2);
  });
});
