import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AdminFleetPage } from "./AdminFleetPage";
import {
  archiveBrand,
  archiveVehicle,
  bulkImportVehicles,
  createBrand,
  createSpecDraft,
  createVehicle,
  fetchAdminBrands,
  fetchAdminVehicles,
  fetchBrandArchiveImpact,
  fetchResearchModels,
  fetchResearchVariants,
  fetchSpecDraft,
  fetchVehicleArchiveImpact,
  patchSpecDraft,
  unarchiveBrand,
  unarchiveVehicle,
  updateVehicle,
} from "../api/adminFleet";
import type { AdminBrand, AdminVehicle, ArchiveImpact } from "../types/adminFleet";
import type {
  ResearchModel,
  ResearchVariant,
  VehicleSpecDraft,
} from "../types/vehicleSpecDraft";

vi.mock("../api/adminFleet", () => ({
  fetchAdminVehicles: vi.fn(),
  fetchAdminBrands: vi.fn(),
  createVehicle: vi.fn(),
  updateVehicle: vi.fn(),
  archiveVehicle: vi.fn(),
  bulkImportVehicles: vi.fn(),
  createBrand: vi.fn(),
  archiveBrand: vi.fn(),
  fetchResearchModels: vi.fn(),
  fetchResearchVariants: vi.fn(),
  createSpecDraft: vi.fn(),
  fetchSpecDraft: vi.fn(),
  patchSpecDraft: vi.fn(),
  fetchBrandArchiveImpact: vi.fn(),
  fetchVehicleArchiveImpact: vi.fn(),
  unarchiveBrand: vi.fn(),
  unarchiveVehicle: vi.fn(),
}));

const mockedFetchAdminVehicles = vi.mocked(fetchAdminVehicles);
const mockedFetchAdminBrands = vi.mocked(fetchAdminBrands);
const mockedCreateVehicle = vi.mocked(createVehicle);
const mockedUpdateVehicle = vi.mocked(updateVehicle);
const mockedArchiveVehicle = vi.mocked(archiveVehicle);
const mockedBulkImportVehicles = vi.mocked(bulkImportVehicles);
const mockedCreateBrand = vi.mocked(createBrand);
const mockedFetchResearchModels = vi.mocked(fetchResearchModels);
const mockedFetchResearchVariants = vi.mocked(fetchResearchVariants);
const mockedCreateSpecDraft = vi.mocked(createSpecDraft);
const mockedFetchSpecDraft = vi.mocked(fetchSpecDraft);
const mockedPatchSpecDraft = vi.mocked(patchSpecDraft);
const mockedArchiveBrand = vi.mocked(archiveBrand);
const mockedFetchBrandArchiveImpact = vi.mocked(fetchBrandArchiveImpact);
const mockedFetchVehicleArchiveImpact = vi.mocked(fetchVehicleArchiveImpact);
const mockedUnarchiveBrand = vi.mocked(unarchiveBrand);
const mockedUnarchiveVehicle = vi.mocked(unarchiveVehicle);

const NO_VEHICLE_IMPACT: ArchiveImpact = { action: "archive", counts: { subscription_plans: 0 }, skipped: [] };

const brand: AdminBrand = {
  id: 1,
  name: "Toyota",
  tier_code: "1",
  is_active: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function makeVehicle(overrides: Partial<AdminVehicle> = {}): AdminVehicle {
  return {
    id: 1,
    brand: 1,
    brand_name: "Toyota",
    name: "Camry",
    trim: "2.5V",
    body_segment: "sedan",
    model_year: 2026,
    msrp: "180000.00",
    min_downpayment: "18000.00",
    engine_capacity_kw: "150.00",
    powertrain: "petrol",
    engine_capacity_cc: 1498,
    spec_complete: true,
    thumbnail_url: "https://example.com/camry.jpg",
    is_active: true,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

// Redesign UI-6a: a row's actions sit behind "Actions for {row}", and each list
// shows Active rows by default (Archived / All one click away).
async function chooseRowAction(user: ReturnType<typeof userEvent.setup>, rowName: string, action: string, scope?: HTMLElement) {
  await user.click((scope ? within(scope) : screen).getByRole("button", { name: `Actions for ${rowName}` }));
  await user.click(await screen.findByRole("menuitem", { name: action }));
}

async function showRows(user: ReturnType<typeof userEvent.setup>, section: "Vehicles" | "Brands", filter: "Active" | "Archived" | "All") {
  const region = await screen.findByRole("region", { name: section });
  await user.click(within(region).getByRole("button", { name: new RegExp(`^${filter} \\(`) }));
}

describe("AdminFleetPage", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    mockedFetchAdminBrands.mockResolvedValue([brand]);
    mockedFetchVehicleArchiveImpact.mockResolvedValue(NO_VEHICLE_IMPACT);
  });

  it("renders the vehicle list once loaded", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([makeVehicle()]);

    render(<AdminFleetPage />);

    expect(await screen.findByText("Camry")).toBeInTheDocument();
    expect(screen.getAllByText("Toyota").length).toBeGreaterThan(0);
  });

  it("preserves every valid field's value when the server rejects one field on create", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([]);
    mockedCreateVehicle.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 400, data: { msrp: ["MSRP must be between RM0.01 and RM100,000,000.00."] } },
    });
    const user = userEvent.setup();

    render(<AdminFleetPage />);
    await user.click(await screen.findByRole("button", { name: "Add Vehicle" }));
    // Scoped to the vehicle form itself - the always-mounted Brand
    // section below also has a "Name" field, so an unscoped
    // getByLabelText("Name") would match both.
    const form = (await screen.findByRole("button", { name: "Create Vehicle" })).closest("form");
    if (!form) throw new Error("vehicle form not found");
    const formScope = within(form);

    await user.selectOptions(formScope.getByLabelText("Brand"), "1");
    await user.type(formScope.getByLabelText("Name"), "Camry");
    await user.type(formScope.getByLabelText("Trim"), "2.5V");
    await user.type(formScope.getByLabelText("MSRP (RM)"), "999999999999.00");
    await user.click(formScope.getByRole("button", { name: "Create Vehicle" }));

    expect(
      await screen.findByText("MSRP must be between RM0.01 and RM100,000,000.00."),
    ).toBeInTheDocument();
    // Every other already-entered value survives the failed submit.
    expect(formScope.getByLabelText("Name")).toHaveValue("Camry");
    expect(formScope.getByLabelText("Trim")).toHaveValue("2.5V");
    expect(formScope.getByLabelText("MSRP (RM)")).toHaveValue("999999999999.00");
  });

  it("archives a vehicle only after the confirm dialog is accepted", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([makeVehicle()]);
    mockedArchiveVehicle.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();

    render(<AdminFleetPage />);
    const vehicleRow = (await screen.findByText("Camry")).closest("tr");
    if (!vehicleRow) throw new Error("vehicle row not found");

    // Scoped to the vehicle's own row menu (the Brands table has its own).
    await chooseRowAction(user, "Toyota Camry 2.5V", "Archive", vehicleRow);
    expect(mockedArchiveVehicle).not.toHaveBeenCalled();

    const dialog = await screen.findByRole("alertdialog");
    await within(dialog).findByText("Archiving Toyota Camry 2.5V will not archive anything else.");
    await user.click(within(dialog).getByRole("button", { name: "Archive" }));

    expect(mockedArchiveVehicle).toHaveBeenCalledWith(1);
    // Redesign UI-6a: the archived row leaves the default Active view, and shows under Archived.
    await waitFor(() => expect(screen.queryByText("Camry")).not.toBeInTheDocument());
    await showRows(user, "Vehicles", "Archived");
    expect(within((await screen.findByText("Camry")).closest("tr") as HTMLElement).getByText("Archived")).toBeInTheDocument();
  });

  // --- Cascade archive (apps.vehicles.archiving) -------------------------

  it("shows the real cascade counts in the brand archive dialog, then re-reads the fleet", async () => {
    const volvo: AdminBrand = { ...brand, id: 11, name: "Volvo" };
    mockedFetchAdminBrands.mockReset();
    mockedFetchAdminBrands
      .mockResolvedValueOnce([volvo])
      .mockResolvedValueOnce([{ ...volvo, is_active: false }]);
    mockedFetchAdminVehicles
      .mockResolvedValueOnce([makeVehicle({ id: 13, brand: 11, brand_name: "Volvo", name: "XC90" })])
      .mockResolvedValueOnce([makeVehicle({ id: 13, brand: 11, brand_name: "Volvo", name: "XC90", is_active: false })]);
    mockedFetchBrandArchiveImpact.mockResolvedValueOnce({
      action: "archive",
      counts: { vehicles: 3, interest_rates: 1, residual_value_rows: 12, penalty_rules: 1, subscription_plans: 3 },
      skipped: [],
    });
    mockedArchiveBrand.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();

    render(<AdminFleetPage />);
    const brandRow = (await screen.findAllByText("Volvo")).map((cell) => cell.closest("tr")).find(
      (row) => row && within(row).queryByText("XC90") === null,
    );
    if (!brandRow) throw new Error("brand row not found");
    await chooseRowAction(user, "Volvo", "Archive", brandRow);

    const dialog = await screen.findByRole("alertdialog");
    expect(mockedFetchBrandArchiveImpact).toHaveBeenCalledWith(11);
    expect(
      await within(dialog).findByText(
        "Archiving Volvo will also archive 3 vehicles, 1 interest rate, 12 residual value rows, 1 penalty rule and 3 subscription plans. Reactivating it later brings exactly these back.",
      ),
    ).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Archive" }));

    expect(mockedArchiveBrand).toHaveBeenCalledWith(11);
    // The cascaded vehicle now shows as Archived too (re-read from the API) -
    // under All, since the default view is Active (redesign UI-6a).
    await showRows(user, "Vehicles", "All");
    await showRows(user, "Brands", "All");
    expect(await screen.findAllByText("Archived")).toHaveLength(2);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Volvo archived, along with 3 vehicles, 1 interest rate, 12 residual value rows, 1 penalty rule and 3 subscription plans.",
    );
  });

  it("shows the vehicle's subscription plan count in its archive dialog", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([makeVehicle()]);
    mockedFetchVehicleArchiveImpact.mockResolvedValueOnce({
      action: "archive",
      counts: { subscription_plans: 1 },
      skipped: [],
    });
    const user = userEvent.setup();

    render(<AdminFleetPage />);
    const vehicleRow = (await screen.findByText("Camry")).closest("tr");
    if (!vehicleRow) throw new Error("vehicle row not found");
    await chooseRowAction(user, "Toyota Camry 2.5V", "Archive", vehicleRow);

    expect(mockedFetchVehicleArchiveImpact).toHaveBeenCalledWith(1);
    expect(
      await screen.findByText(
        "Archiving Toyota Camry 2.5V will also archive 1 subscription plan. Reactivating it later brings exactly these back.",
      ),
    ).toBeInTheDocument();
  });

  it("reactivates an archived brand, listing what comes back and what the uniqueness guard skips", async () => {
    const volvo: AdminBrand = { ...brand, id: 11, name: "Volvo", is_active: false };
    mockedFetchAdminBrands.mockReset();
    mockedFetchAdminBrands.mockResolvedValueOnce([volvo]).mockResolvedValueOnce([{ ...volvo, is_active: true }]);
    mockedFetchAdminVehicles.mockResolvedValue([]);
    const skipped = {
      resource_type: "policy.InterestRate",
      id: 8,
      label: "Volvo @ 3.0000%",
      reason: "Volvo @ 4.0000% (#9) is already active",
    };
    mockedFetchBrandArchiveImpact.mockResolvedValueOnce({
      action: "restore",
      counts: { vehicles: 1, interest_rates: 0, residual_value_rows: 0, penalty_rules: 0, subscription_plans: 0 },
      skipped: [skipped],
    });
    mockedUnarchiveBrand.mockResolvedValueOnce({
      ...volvo,
      is_active: true,
      cascade: {
        action: "restore",
        counts: { vehicles: 1, interest_rates: 0, residual_value_rows: 0, penalty_rules: 0, subscription_plans: 0 },
        skipped: [skipped],
      },
    });
    const user = userEvent.setup();

    render(<AdminFleetPage />);
    // Redesign UI-6a: an archived brand is listed under Archived / All.
    await showRows(user, "Brands", "All");
    const brandRow = (await screen.findByRole("cell", { name: "Volvo" })).closest("tr");
    if (!brandRow) throw new Error("brand row not found");
    await chooseRowAction(user, "Volvo", "Reactivate", brandRow);

    const dialog = await screen.findByRole("alertdialog");
    expect(
      await within(dialog).findByText("Reactivating Volvo will also restore 1 vehicle archived along with it."),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText("Volvo @ 3.0000% stays archived - Volvo @ 4.0000% (#9) is already active."),
    ).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Reactivate" }));

    expect(mockedUnarchiveBrand).toHaveBeenCalledWith(11);
    const notice = await screen.findByRole("status");
    expect(notice).toHaveTextContent("Volvo reactivated, along with 1 vehicle.");
    expect(notice).toHaveTextContent("Volvo @ 3.0000% stays archived - Volvo @ 4.0000% (#9) is already active.");
    expect(await screen.findByText("Active")).toBeInTheDocument();
  });

  it("reactivates an archived vehicle from its own row", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([makeVehicle({ is_active: false })]);
    mockedFetchVehicleArchiveImpact.mockResolvedValueOnce({
      action: "restore",
      counts: { subscription_plans: 1 },
      skipped: [],
    });
    mockedUnarchiveVehicle.mockResolvedValueOnce({
      ...makeVehicle(),
      cascade: { action: "restore", counts: { subscription_plans: 1 }, skipped: [] },
    });
    const user = userEvent.setup();

    render(<AdminFleetPage />);
    // Redesign UI-6a: an archived vehicle is listed under Archived / All.
    await showRows(user, "Vehicles", "All");
    const vehicleRow = (await screen.findByText("Camry")).closest("tr");
    if (!vehicleRow) throw new Error("vehicle row not found");
    await chooseRowAction(user, "Toyota Camry 2.5V", "Reactivate", vehicleRow);
    const dialog = await screen.findByRole("alertdialog");
    await within(dialog).findByText(
      "Reactivating Toyota Camry 2.5V will also restore 1 subscription plan archived along with it.",
    );
    await user.click(within(dialog).getByRole("button", { name: "Reactivate" }));

    expect(mockedUnarchiveVehicle).toHaveBeenCalledWith(1);
    expect(await within(vehicleRow).findByText("Active")).toBeInTheDocument();
  });

  it("renders the bulk-import report, including per-row error detail", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([]);
    mockedBulkImportVehicles.mockResolvedValueOnce({
      total_rows: 2,
      created_count: 1,
      error_count: 1,
      errors: [{ row: 3, errors: { trim: ["This brand/name/trim combination is duplicated elsewhere in this file."] } }],
      created: [makeVehicle({ id: 2 })],
    });
    const user = userEvent.setup();

    render(<AdminFleetPage />);
    await screen.findByText("Bulk Import");

    const file = new File(["brand,name,trim\n"], "fleet.csv", { type: "text/csv" });
    await user.upload(screen.getByLabelText("Bulk import file"), file);
    await user.click(screen.getByRole("button", { name: "Import" }));

    expect(await screen.findByText("Total rows: 2")).toBeInTheDocument();
    expect(screen.getByText("Created: 1")).toBeInTheDocument();
    expect(screen.getByText("Errors: 1")).toBeInTheDocument();
    expect(
      screen.getByText("This brand/name/trim combination is duplicated elsewhere in this file."),
    ).toBeInTheDocument();
  });

  it("adds a new brand via the brand management section", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([]);
    mockedCreateBrand.mockResolvedValueOnce({
      id: 2,
      name: "Lexus",
      tier_code: "1",
      is_active: true,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });
    const user = userEvent.setup();

    render(<AdminFleetPage />);
    await screen.findByText("Brands");

    await user.type(screen.getByLabelText("Name"), "Lexus");
    await user.type(screen.getByLabelText("Tier code"), "1");
    await user.click(screen.getByRole("button", { name: "Add Brand" }));

    expect(mockedCreateBrand).toHaveBeenCalledWith({ name: "Lexus", tier_code: "1" });
    // Redesign UI-6a: scoped to the Brands table (the new "Filter by brand" select lists it too).
    expect(await within(screen.getByRole("region", { name: "Brands" })).findByRole("cell", { name: "Lexus" })).toBeInTheDocument();
  });

  // Live-walkthrough finding 5: the vehicle Add/Edit form's own Brand
  // select previously reused the SAME unfiltered `brandOptions` the
  // Brands management table needs (which correctly shows archived
  // brands) - every archived brand was listed and selectable there too,
  // labeled "(archived)" but not actually excluded.
  const archivedBrand: AdminBrand = {
    id: 2,
    name: "Proton",
    tier_code: "4",
    is_active: false,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };

  it("excludes archived brands from a freshly-opened Add Vehicle form's Brand options", async () => {
    mockedFetchAdminBrands.mockReset();
    mockedFetchAdminBrands.mockResolvedValue([brand, archivedBrand]);
    mockedFetchAdminVehicles.mockResolvedValueOnce([]);
    const user = userEvent.setup();

    render(<AdminFleetPage />);
    await user.click(await screen.findByRole("button", { name: "Add Vehicle" }));

    const form = (await screen.findByRole("button", { name: "Create Vehicle" })).closest("form");
    if (!form) throw new Error("vehicle form not found");
    const brandSelect = within(form).getByLabelText("Brand") as HTMLSelectElement;
    const optionLabels = Array.from(brandSelect.options).map((option) => option.textContent);

    expect(optionLabels).toContain("Toyota");
    expect(optionLabels).not.toContain("Proton (archived)");
    expect(optionLabels).not.toContain("Proton");
  });

  it("still includes a vehicle's own brand in the Edit Vehicle form, even though it's since been archived", async () => {
    mockedFetchAdminBrands.mockReset();
    mockedFetchAdminBrands.mockResolvedValue([brand, archivedBrand]);
    mockedFetchAdminVehicles.mockResolvedValueOnce([
      makeVehicle({ brand: 2, brand_name: "Proton", name: "Saga", trim: "Standard" }),
    ]);
    const user = userEvent.setup();

    render(<AdminFleetPage />);
    const vehicleRow = (await screen.findByText("Saga")).closest("tr");
    if (!vehicleRow) throw new Error("vehicle row not found");
    await chooseRowAction(user, "Proton Saga Standard", "Edit", vehicleRow);

    const form = (await screen.findByRole("button", { name: "Save Changes" })).closest("form");
    if (!form) throw new Error("vehicle form not found");
    const brandSelect = within(form).getByLabelText("Brand") as HTMLSelectElement;
    const optionLabels = Array.from(brandSelect.options).map((option) => option.textContent);

    // The vehicle's own (now-archived) brand stays selectable...
    expect(optionLabels).toContain("Proton (archived)");
    expect(brandSelect).toHaveValue("2");
    // ...alongside every active brand, same as the Add form.
    expect(optionLabels).toContain("Toyota");
  });

  // --- Audit batch 6: the "Edit vehicle" link on Vehicle Readiness --------------

  it("opens that vehicle's edit form straight away when reached from /admin/fleet?edit=<id>", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([
      makeVehicle({ id: 1, name: "Camry" }),
      makeVehicle({ id: 7, name: "Alphard", trim: "2.4 Executive Lounge" }),
    ]);
    window.history.pushState({}, "", "/admin/fleet?edit=7");
    try {
      render(<AdminFleetPage />);

      const form = (await screen.findByRole("button", { name: "Save Changes" })).closest("form");
      if (!form) throw new Error("vehicle form not found");
      expect(within(form).getByLabelText("Name")).toHaveValue("Alphard");
      expect(within(form).getByLabelText("Trim")).toHaveValue("2.4 Executive Lounge");
    } finally {
      window.history.pushState({}, "", "/");
    }
  });

  it("opens no form on a plain visit, or when the id in the link isn't in the list", async () => {
    mockedFetchAdminVehicles.mockResolvedValue([makeVehicle({ id: 1, name: "Camry" })]);
    window.history.pushState({}, "", "/admin/fleet?edit=999");
    try {
      render(<AdminFleetPage />);

      expect(await screen.findByText("Camry")).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Save Changes" })).not.toBeInTheDocument();
    } finally {
      window.history.pushState({}, "", "/");
    }
  });

  // --- Audit batch 1: powertrain + engine capacity (cc), power output (kW) ---

  async function openAddVehicleForm(user: ReturnType<typeof userEvent.setup>) {
    render(<AdminFleetPage />);
    await user.click(await screen.findByRole("button", { name: "Add Vehicle" }));
    const form = (await screen.findByRole("button", { name: "Create Vehicle" })).closest("form");
    if (!form) throw new Error("vehicle form not found");
    return within(form);
  }

  it("labels the kW field as power output and offers a Powertrain select and a cc input", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([]);
    const user = userEvent.setup();

    const formScope = await openAddVehicleForm(user);

    expect(formScope.getByLabelText("Power output (kW)")).toBeInTheDocument();
    expect(formScope.queryByLabelText("Engine capacity (kW)")).not.toBeInTheDocument();
    const powertrain = formScope.getByLabelText("Powertrain") as HTMLSelectElement;
    expect(Array.from(powertrain.options).map((option) => option.textContent)).toEqual([
      "Select...",
      "Petrol",
      "Diesel",
      "Mild hybrid (MHEV)",
      "Hybrid (HEV)",
      "Plug-in hybrid (PHEV)",
      "Battery electric (BEV)",
    ]);
    expect(formScope.getByLabelText("Engine capacity (cc)")).toBeEnabled();
  });

  it("disables and clears the cc input when Battery electric is chosen, and re-enables it for any other powertrain", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([]);
    const user = userEvent.setup();
    const formScope = await openAddVehicleForm(user);
    const cc = formScope.getByLabelText("Engine capacity (cc)");

    await user.selectOptions(formScope.getByLabelText("Powertrain"), "petrol");
    await user.type(cc, "1998");
    expect(cc).toHaveValue(1998);

    await user.selectOptions(formScope.getByLabelText("Powertrain"), "bev");
    expect(cc).toBeDisabled();
    expect(cc).toHaveValue(null); // number input, cleared
    expect(formScope.getByText("Not applicable to a battery electric vehicle.")).toBeInTheDocument();

    await user.selectOptions(formScope.getByLabelText("Powertrain"), "phev");
    expect(cc).toBeEnabled();
    expect(cc).toHaveValue(null); // stays cleared - nothing is brought back
  });

  // --- Run 1 fix batch 3: road-tax registration class ------------------------

  it("offers the road-tax class with the VOC help text, defaulting to the body type's usual class", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([]);
    mockedCreateVehicle.mockResolvedValue(makeVehicle({ id: 9 }));
    const user = userEvent.setup();
    const formScope = await openAddVehicleForm(user);

    const select = formScope.getByLabelText("Road-tax class") as HTMLSelectElement;
    expect(Array.from(select.options).map((o) => [o.value, o.textContent])).toEqual([
      ["", "Usual for the body type"],
      ["saloon", "Saloon"],
      ["non_saloon", "Non-saloon"],
    ]);
    expect(select).toHaveValue("");
    expect(select).toHaveAccessibleDescription(
      "Use the class on the car's registration card (VOC). Body type is only the default.",
    );
    expect(formScope.queryByText("Check road-tax class on the VOC")).not.toBeInTheDocument();

    await user.click(formScope.getByRole("button", { name: "Create Vehicle" }));
    // Blank: the server fills in the body type's usual class.
    await waitFor(() => expect(mockedCreateVehicle).toHaveBeenCalledTimes(1));
    expect(mockedCreateVehicle).toHaveBeenLastCalledWith(expect.objectContaining({ road_tax_class: "" }));
  });

  it("sends an explicit class and flags it for a check against the VOC", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([]);
    mockedCreateVehicle.mockResolvedValue(makeVehicle({ id: 9 }));
    const user = userEvent.setup();
    const formScope = await openAddVehicleForm(user);

    await user.selectOptions(formScope.getByLabelText("Road-tax class"), "non_saloon");
    expect(formScope.getByText("Check road-tax class on the VOC")).toBeInTheDocument();
    await user.click(formScope.getByRole("button", { name: "Create Vehicle" }));

    await waitFor(() => expect(mockedCreateVehicle).toHaveBeenCalledTimes(1));
    expect(mockedCreateVehicle).toHaveBeenLastCalledWith(expect.objectContaining({ road_tax_class: "non_saloon" }));
  });

  it("flags a crossover for a VOC check, and has no class for an electric car", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([]);
    const user = userEvent.setup();
    const formScope = await openAddVehicleForm(user);

    await user.selectOptions(formScope.getByLabelText("Body segment"), "crossover");
    expect(formScope.getByText("Check road-tax class on the VOC")).toBeInTheDocument();

    await user.selectOptions(formScope.getByLabelText("Powertrain"), "bev");
    expect(formScope.getByLabelText("Road-tax class")).toBeDisabled();
    expect(formScope.getByText("Electric cars are taxed by motor kW, not by class.")).toBeInTheDocument();
    expect(formScope.queryByText("Check road-tax class on the VOC")).not.toBeInTheDocument();
  });

  it("marks a listed car whose class differs from its body type, as Vehicle Readiness does", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([
      makeVehicle({ id: 1, name: "Camry", road_tax_class: "saloon", road_tax_class_is_default: true }),
      makeVehicle({
        id: 2, name: "RAV4", body_segment: "suv", road_tax_class: "saloon", road_tax_class_is_default: false,
      }),
    ]);

    render(<AdminFleetPage />);

    const rav4Row = (await screen.findByText("RAV4")).closest("tr");
    const camryRow = screen.getByText("Camry").closest("tr");
    expect(within(rav4Row as HTMLElement).getByText("Check road-tax class on the VOC")).toBeInTheDocument();
    expect(within(camryRow as HTMLElement).queryByText("Check road-tax class on the VOC")).not.toBeInTheDocument();
  });

  // --- Run 1 fix batch 5: optional model year, UC010 messages, edit conflicts ----

  it("says 'Vehicle added successfully.' after a create", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([]);
    mockedCreateVehicle.mockResolvedValue(makeVehicle({ id: 9 }));
    const user = userEvent.setup();
    const formScope = await openAddVehicleForm(user);

    await user.click(formScope.getByRole("button", { name: "Create Vehicle" }));

    expect(await screen.findByText("Vehicle added successfully.")).toBeInTheDocument();
    // A blank model year goes over as null, never "".
    expect(mockedCreateVehicle).toHaveBeenLastCalledWith(expect.objectContaining({ model_year: null }));
  });

  it("edits a car with no model year, sends the updated_at it loaded, and says it was updated", async () => {
    const loaded = makeVehicle({ id: 7, name: "ES", model_year: null, updated_at: "2026-10-13T09:00:00.123456+08:00" });
    mockedFetchAdminVehicles.mockResolvedValueOnce([loaded]);
    mockedUpdateVehicle.mockResolvedValue({ ...loaded, msrp: "359888.00" });
    const user = userEvent.setup();
    render(<AdminFleetPage />);

    await screen.findByText("ES");
    await chooseRowAction(user, "Toyota ES 2.5V", "Edit");
    const msrp = screen.getByLabelText("MSRP (RM)");
    await user.clear(msrp);
    await user.type(msrp, "359888.00");
    await user.click(screen.getByRole("button", { name: "Save Changes" }));

    expect(await screen.findByText("Vehicle updated successfully.")).toBeInTheDocument();
    expect(mockedUpdateVehicle).toHaveBeenCalledWith(
      7,
      expect.objectContaining({ msrp: "359888.00", model_year: null, updated_at: "2026-10-13T09:00:00.123456+08:00" }),
    );
  });

  it("on a 409 says someone else changed it and keeps every typed value on screen", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([makeVehicle({ id: 7 })]);
    mockedUpdateVehicle.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 409,
        data: { detail: "This record was changed by someone else. Reload to see the latest version." },
      },
    });
    const user = userEvent.setup();
    render(<AdminFleetPage />);

    await screen.findByText("Camry");
    await chooseRowAction(user, "Toyota Camry 2.5V", "Edit");
    const msrp = screen.getByLabelText("MSRP (RM)");
    await user.clear(msrp);
    await user.type(msrp, "199999.00");
    await user.click(screen.getByRole("button", { name: "Save Changes" }));

    expect(
      await screen.findByText("This record was changed by someone else. Reload to see the latest version."),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("MSRP (RM)")).toHaveValue("199999.00");
    expect(screen.queryByText("Vehicle updated successfully.")).not.toBeInTheDocument();
  });

  it("sends a BEV's blank cc as null, not an empty string", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([]);
    mockedCreateVehicle.mockResolvedValue(makeVehicle({ id: 9 }));
    const user = userEvent.setup();
    const formScope = await openAddVehicleForm(user);

    await user.selectOptions(formScope.getByLabelText("Powertrain"), "bev");
    await user.click(formScope.getByRole("button", { name: "Create Vehicle" }));

    await waitFor(() => expect(mockedCreateVehicle).toHaveBeenCalledTimes(1));
    expect(mockedCreateVehicle).toHaveBeenLastCalledWith(
      expect.objectContaining({ powertrain: "bev", engine_capacity_cc: null }),
    );
  });

  it("sends the cc as a number for a petrol car", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([]);
    mockedCreateVehicle.mockResolvedValue(makeVehicle({ id: 9 }));
    const user = userEvent.setup();
    const formScope = await openAddVehicleForm(user);

    await user.selectOptions(formScope.getByLabelText("Brand"), "1");
    await user.type(formScope.getByLabelText("Name"), "3 Series");
    await user.type(formScope.getByLabelText("Trim"), "320i Sport");
    await user.selectOptions(formScope.getByLabelText("Body segment"), "sedan");
    await user.type(formScope.getByLabelText("MSRP (RM)"), "265800.00");
    await user.type(formScope.getByLabelText("Power output (kW)"), "135.00");
    await user.selectOptions(formScope.getByLabelText("Powertrain"), "petrol");
    await user.type(formScope.getByLabelText("Engine capacity (cc)"), "1998");
    await user.click(formScope.getByRole("button", { name: "Create Vehicle" }));

    await waitFor(() => expect(mockedCreateVehicle).toHaveBeenCalledTimes(1));
    expect(mockedCreateVehicle).toHaveBeenLastCalledWith(
      expect.objectContaining({
        engine_capacity_kw: "135.00",
        powertrain: "petrol",
        engine_capacity_cc: 1998,
      }),
    );
  });

  it("shows a Needs specs badge on rows whose spec_complete is false, and only on those", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([
      makeVehicle({ id: 1, name: "Camry" }),
      makeVehicle({
        id: 2, name: "Volvo-ish", trim: "B5", powertrain: "", engine_capacity_cc: null, spec_complete: false,
      }),
      makeVehicle({
        id: 3, name: "Old Archived", trim: "X", powertrain: "", engine_capacity_cc: null,
        spec_complete: false, is_active: false,
      }),
    ]);

    const user = userEvent.setup();
    render(<AdminFleetPage />);

    // Redesign UI-6a: the archived row is listed under All.
    await screen.findByText("Camry");
    expect(screen.getAllByText("Needs specs")).toHaveLength(1); // the default view: active rows
    await showRows(user, "Vehicles", "All");
    const badges = await screen.findAllByText("Needs specs");
    expect(badges).toHaveLength(2); // incl. the archived row - it still lacks specs
    const rowOf = async (name: string) => (await screen.findByText(name)).closest("tr") as HTMLElement;
    expect(within(await rowOf("Volvo-ish")).getByText("Needs specs")).toBeInTheDocument();
    expect(within(await rowOf("Old Archived")).getByText("Needs specs")).toBeInTheDocument();
    expect(within(await rowOf("Camry")).queryByText("Needs specs")).not.toBeInTheDocument();
  });

  it("opens a legacy row for editing with powertrain and cc blank, never guessed", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([
      makeVehicle({ powertrain: "", engine_capacity_cc: null, spec_complete: false }),
    ]);
    const user = userEvent.setup();

    render(<AdminFleetPage />);
    const row = (await screen.findByText("Camry")).closest("tr");
    if (!row) throw new Error("vehicle row not found");
    await chooseRowAction(user, "Toyota Camry 2.5V", "Edit", row);

    const form = (await screen.findByRole("button", { name: "Save Changes" })).closest("form");
    if (!form) throw new Error("vehicle form not found");
    expect(within(form).getByLabelText("Powertrain")).toHaveValue("");
    expect(within(form).getByLabelText("Engine capacity (cc)")).toHaveValue(null);
    expect(within(form).getByLabelText("Power output (kW)")).toHaveValue("150.00");
  });

  it("lists the new import columns in the bulk-import help text", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([]);

    render(<AdminFleetPage />);

    const help = await screen.findByText(/Required columns:/);
    expect(help).toHaveTextContent("powertrain (petrol, diesel, mild_hybrid, hybrid, phev or bev)");
    expect(help).toHaveTextContent("engine_capacity_cc");
    expect(help).toHaveTextContent("engine_capacity_kw (power output in kW)");
  });

  // --- F010 optional stretch goal: "Fetch Spec Draft (beta)" ------------
  // Brand -> Model -> Variant picker over paultan.org's Car Buyer's Guide.

  const MODEL_URL = "https://paultan.org/research/toyota/alphard/";
  const VARIANT_URL = "https://paultan.org/research/toyota/alphard/ah40/2-5l-2026/";

  const researchModels: ResearchModel[] = [
    {
      name: "Toyota Estima",
      url: "https://paultan.org/research/toyota/estima/",
      price_text: "RM289,000",
      on_sale: false,
    },
    { name: "Toyota Alphard", url: MODEL_URL, price_text: "RM438,000–RM493,000", on_sale: true },
  ];

  const researchVariants: ResearchVariant[] = [
    {
      name: "Toyota Alphard 2.5L",
      url: VARIANT_URL,
      generation: "ah40",
      year: 2026,
      msrp: "438000",
      power_hp: 179,
      on_sale: true,
    },
    // Card name without the model prefix - the label falls back to
    // dropping just the brand.
    {
      name: "Toyota 2.5L Executive Lounge",
      url: "https://paultan.org/research/toyota/alphard/ah40/2-5l-executive-lounge-2026/",
      generation: "ah40",
      year: 2026,
      msrp: "493000",
      power_hp: null,
      on_sale: true,
    },
    {
      name: "Toyota Alphard 2.5L",
      url: "https://paultan.org/research/toyota/alphard/ah30/2-5l-2022/",
      generation: "ah30",
      year: 2022,
      msrp: "461000",
      power_hp: 180,
      on_sale: false,
    },
  ];

  function makeDraft(overrides: Partial<VehicleSpecDraft> = {}): VehicleSpecDraft {
    return {
      id: 1,
      brand: 1,
      brand_name: "Toyota",
      model_name_query: "Alphard",
      trim_query: "2.5L",
      status: "ready",
      source_url: VARIANT_URL,
      proposed_data: { body_segment: "mpv", model_year: "2026" },
      missing_fields: ["msrp", "engine_capacity_kw"],
      fetched_at: "2026-01-01T00:00:00Z",
      error_message: "",
      approved_vehicle: null,
      requested_by: 1,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      ...overrides,
    };
  }

  function optionLabels(select: HTMLElement): (string | null)[] {
    return Array.from((select as HTMLSelectElement).options).map((option) => option.textContent);
  }

  async function openPanelAndFindModels(user: ReturnType<typeof userEvent.setup>) {
    render(<AdminFleetPage />);
    await user.click(await screen.findByRole("button", { name: "Fetch Spec Draft (beta)" }));
    await user.selectOptions(screen.getByLabelText("Brand"), "1");
    await user.click(screen.getByRole("button", { name: "Find models" }));
  }

  async function pickVariant(user: ReturnType<typeof userEvent.setup>) {
    mockedFetchResearchModels.mockResolvedValueOnce({ brand_slug: "toyota", models: researchModels });
    mockedFetchResearchVariants.mockResolvedValueOnce({ variants: researchVariants });
    await openPanelAndFindModels(user);
    await user.selectOptions(await screen.findByLabelText("Model"), MODEL_URL);
    await waitFor(() => expect(screen.getByLabelText("Variant")).not.toBeDisabled());
    await user.selectOptions(screen.getByLabelText("Variant"), VARIANT_URL);
  }

  it("loads the brand's models (on-sale first, with price range) after Find models", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([]);
    mockedFetchResearchModels.mockResolvedValueOnce({ brand_slug: "toyota", models: researchModels });
    const user = userEvent.setup();

    await openPanelAndFindModels(user);

    expect(mockedFetchResearchModels).toHaveBeenCalledWith("Toyota");
    const modelSelect = await screen.findByLabelText("Model");
    await waitFor(() => expect(modelSelect).not.toBeDisabled());
    expect(optionLabels(modelSelect)).toEqual([
      "Select a model...",
      "Toyota Alphard · RM438,000–RM493,000",
      "Toyota Estima · RM289,000 (no longer on sale)",
    ]);
  });

  it("shows the API's message when the brand has no buyer's-guide models", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([]);
    mockedFetchResearchModels.mockResolvedValueOnce({
      brand_slug: "toyota",
      models: [],
      message: "No paultan.org buyer's-guide page for this brand",
    });
    const user = userEvent.setup();

    await openPanelAndFindModels(user);

    expect(await screen.findByText("No paultan.org buyer's-guide page for this brand")).toBeInTheDocument();
    expect(screen.getByLabelText("Model")).toBeDisabled();
  });

  it("loads the chosen model's variants, labeled short name · year · price · hp", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([]);
    mockedFetchResearchModels.mockResolvedValueOnce({ brand_slug: "toyota", models: researchModels });
    mockedFetchResearchVariants.mockResolvedValueOnce({ variants: researchVariants });
    const user = userEvent.setup();

    await openPanelAndFindModels(user);
    await user.selectOptions(await screen.findByLabelText("Model"), MODEL_URL);

    expect(mockedFetchResearchVariants).toHaveBeenCalledWith(MODEL_URL);
    const variantSelect = screen.getByLabelText("Variant");
    await waitFor(() => expect(variantSelect).not.toBeDisabled());
    expect(optionLabels(variantSelect)).toEqual([
      "Select a variant...",
      "2.5L · 2026 · RM438,000 · 179 hp",
      "2.5L Executive Lounge · 2026 · RM493,000",
      "2.5L · 2022 · RM461,000 · 180 hp (no longer on sale)",
    ]);
  });

  it("keeps Fetch Spec Draft disabled until a variant is chosen, then posts its source_url", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([]);
    mockedFetchResearchModels.mockResolvedValueOnce({ brand_slug: "toyota", models: researchModels });
    mockedFetchResearchVariants.mockResolvedValueOnce({ variants: researchVariants });
    mockedCreateSpecDraft.mockResolvedValueOnce(makeDraft({ status: "pending" }));
    const user = userEvent.setup();

    await openPanelAndFindModels(user);
    const fetchButton = screen.getByRole("button", { name: "Fetch Spec Draft" });
    expect(fetchButton).toBeDisabled();

    await user.selectOptions(await screen.findByLabelText("Model"), MODEL_URL);
    expect(fetchButton).toBeDisabled();

    await waitFor(() => expect(screen.getByLabelText("Variant")).not.toBeDisabled());
    await user.selectOptions(screen.getByLabelText("Variant"), VARIANT_URL);
    expect(fetchButton).toBeEnabled();

    await user.click(fetchButton);
    expect(mockedCreateSpecDraft).toHaveBeenCalledWith({
      brand: 1,
      source_url: VARIANT_URL,
      model_name_query: "Alphard",
      trim_query: "2.5L",
    });
  });

  it("shows a missing-field badge for each field in missing_fields, and pre-fills the rest, once the draft is READY", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([]);
    mockedCreateSpecDraft.mockResolvedValueOnce(makeDraft({ status: "pending" }));
    mockedFetchSpecDraft.mockResolvedValueOnce(makeDraft());
    const user = userEvent.setup();

    await pickVariant(user);
    await user.click(screen.getByRole("button", { name: "Fetch Spec Draft" }));

    // Polling resolves the draft as READY within one ~2s tick.
    await waitFor(() => expect(screen.getByRole("heading", { name: "Add Vehicle" })).toBeInTheDocument(), {
      timeout: 5000,
    });
    const form = screen.getByRole("button", { name: "Create Vehicle" }).closest("form");
    if (!form) throw new Error("vehicle form not found");
    const formScope = within(form);

    // Successfully-fetched fields are pre-filled, plus Name/Trim from the
    // picked model/variant...
    expect(formScope.getByLabelText("Name")).toHaveValue("Alphard");
    expect(formScope.getByLabelText("Trim")).toHaveValue("2.5L");
    expect(formScope.getByLabelText("Body segment")).toHaveValue("mpv");
    expect(formScope.getByLabelText("Model year")).toHaveValue(2026);
    // ...and the two fields missing from the source page each get their
    // own badge, staying blank rather than looking like a real fetched
    // value.
    expect(formScope.getByLabelText("MSRP (RM)")).toHaveValue("");
    expect(formScope.getByLabelText("Power output (kW)")).toHaveValue("");
    expect(formScope.getAllByText("Not found - please fill in")).toHaveLength(2);

    // The source link is shown so the admin can cross-check it.
    expect(screen.getByRole("link", { name: VARIANT_URL })).toHaveAttribute("href", VARIANT_URL);

    // Every field - fetched or missing - stays fully editable, never
    // read-only.
    expect(formScope.getByLabelText("Body segment")).not.toBeDisabled();
    expect(formScope.getByLabelText("MSRP (RM)")).not.toHaveAttribute("readonly");
    await user.clear(formScope.getByLabelText("MSRP (RM)"));
    await user.type(formScope.getByLabelText("MSRP (RM)"), "350000.00");
    expect(formScope.getByLabelText("MSRP (RM)")).toHaveValue("350000.00");
  });

  it("opens a completely blank form (brand pre-filled) when the draft is NOT_FOUND", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([]);
    mockedCreateSpecDraft.mockResolvedValueOnce(makeDraft({ status: "pending" }));
    mockedFetchSpecDraft.mockResolvedValueOnce(
      makeDraft({ status: "not_found", proposed_data: {}, missing_fields: [] }),
    );
    const user = userEvent.setup();

    await pickVariant(user);
    await user.click(screen.getByRole("button", { name: "Fetch Spec Draft" }));

    await waitFor(() => expect(screen.getByRole("heading", { name: "Add Vehicle" })).toBeInTheDocument(), {
      timeout: 5000,
    });
    expect(
      screen.getByText("No matching spec page was found - fill in the form manually below."),
    ).toBeInTheDocument();
    // Scoped to the vehicle form itself - the always-mounted Brand
    // section below also has its own "Name" field.
    const form = screen.getByRole("button", { name: "Create Vehicle" }).closest("form");
    if (!form) throw new Error("vehicle form not found");
    const formScope = within(form);
    expect(formScope.getByLabelText("Brand")).toHaveValue("1");
    expect(formScope.getByLabelText("Name")).toHaveValue("");
    expect(formScope.getByLabelText("MSRP (RM)")).toHaveValue("");
  });

  it("stops polling on a FAILED draft, shows its error, and falls back to the blank form", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([]);
    mockedCreateSpecDraft.mockResolvedValueOnce(makeDraft({ status: "pending" }));
    mockedFetchSpecDraft.mockResolvedValue(
      makeDraft({
        status: "failed",
        proposed_data: {},
        missing_fields: [],
        error_message: "TimeoutError: Page.goto: Timeout 20000ms exceeded.",
      }),
    );
    const user = userEvent.setup();

    await pickVariant(user);
    await user.click(screen.getByRole("button", { name: "Fetch Spec Draft" }));

    await waitFor(() => expect(screen.getByRole("heading", { name: "Add Vehicle" })).toBeInTheDocument(), {
      timeout: 5000,
    });
    expect(screen.getByText(/TimeoutError: Page\.goto: Timeout 20000ms exceeded\./)).toBeInTheDocument();
    const form = screen.getByRole("button", { name: "Create Vehicle" }).closest("form");
    if (!form) throw new Error("vehicle form not found");
    const formScope = within(form);
    expect(formScope.getByLabelText("Brand")).toHaveValue("1");
    expect(formScope.getByLabelText("Name")).toHaveValue("");
    expect(formScope.getByLabelText("MSRP (RM)")).toHaveValue("");
    expect(formScope.queryByText("Not found - please fill in")).not.toBeInTheDocument();

    // No further polls after the terminal FAILED status (one more ~2s
    // interval would otherwise have fired by now).
    await new Promise((resolve) => setTimeout(resolve, 2500));
    expect(mockedFetchSpecDraft).toHaveBeenCalledTimes(1);
  }, 15000);

  it("saves via the exact same createVehicle() call as manual entry, then fire-and-forget PATCHes the draft to approved", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([]);
    mockedCreateSpecDraft.mockResolvedValueOnce(makeDraft({ status: "pending" }));
    mockedFetchSpecDraft.mockResolvedValueOnce(makeDraft());
    mockedCreateVehicle.mockResolvedValueOnce(
      makeVehicle({ id: 9, name: "Alphard", trim: "2.5L", body_segment: "mpv" }),
    );
    mockedPatchSpecDraft.mockResolvedValueOnce(makeDraft({ status: "approved", approved_vehicle: 9 }));
    const user = userEvent.setup();

    await pickVariant(user);
    await user.click(screen.getByRole("button", { name: "Fetch Spec Draft" }));

    await waitFor(() => expect(screen.getByRole("heading", { name: "Add Vehicle" })).toBeInTheDocument(), {
      timeout: 5000,
    });
    await user.type(screen.getByLabelText("MSRP (RM)"), "350000.00");
    await user.type(screen.getByLabelText("Power output (kW)"), "200.00");
    await user.click(screen.getByRole("button", { name: "Create Vehicle" }));

    await waitFor(() => expect(mockedCreateVehicle).toHaveBeenCalledTimes(1));
    expect(mockedPatchSpecDraft).toHaveBeenCalledWith(1, { status: "approved", approved_vehicle: 9 });
  });

  it("pre-fills powertrain and cc from a READY draft, with a Not found badge only for what the page didn't say", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([]);
    mockedCreateSpecDraft.mockResolvedValueOnce(makeDraft({ status: "pending" }));
    mockedFetchSpecDraft.mockResolvedValueOnce(
      makeDraft({
        proposed_data: { body_segment: "mpv", model_year: "2026", powertrain: "petrol", engine_capacity_cc: "2393" },
        // The page gave a cc and a clear Fuel line, but no price or power.
        missing_fields: ["msrp", "engine_capacity_kw"],
      }),
    );
    const user = userEvent.setup();

    await pickVariant(user);
    await user.click(screen.getByRole("button", { name: "Fetch Spec Draft" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Add Vehicle" })).toBeInTheDocument(), {
      timeout: 5000,
    });
    const form = screen.getByRole("button", { name: "Create Vehicle" }).closest("form");
    if (!form) throw new Error("vehicle form not found");
    const formScope = within(form);

    expect(formScope.getByLabelText("Powertrain")).toHaveValue("petrol");
    expect(formScope.getByLabelText("Engine capacity (cc)")).toHaveValue(2393);
    expect(formScope.getAllByText("Not found - please fill in")).toHaveLength(2); // msrp + power output only
  });

  it("flags an ambiguous powertrain as not found and leaves it for the admin to pick", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([]);
    mockedCreateSpecDraft.mockResolvedValueOnce(makeDraft({ status: "pending" }));
    mockedFetchSpecDraft.mockResolvedValueOnce(
      makeDraft({
        proposed_data: { body_segment: "sedan", model_year: "2026", msrp: "292888", engine_capacity_kw: "147.84", engine_capacity_cc: "1496" },
        missing_fields: ["powertrain"], // paultan said only "Petrol Hybrid/REV"
      }),
    );
    const user = userEvent.setup();

    await pickVariant(user);
    await user.click(screen.getByRole("button", { name: "Fetch Spec Draft" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Add Vehicle" })).toBeInTheDocument(), {
      timeout: 5000,
    });
    const form = screen.getByRole("button", { name: "Create Vehicle" }).closest("form");
    if (!form) throw new Error("vehicle form not found");
    const formScope = within(form);

    expect(formScope.getByLabelText("Powertrain")).toHaveValue("");
    expect(formScope.getByLabelText("Engine capacity (cc)")).toHaveValue(1496);
    expect(formScope.getAllByText("Not found - please fill in")).toHaveLength(1);
  });

  it("pre-fills a BEV draft with the cc input disabled and no cc badge", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([]);
    mockedCreateSpecDraft.mockResolvedValueOnce(makeDraft({ status: "pending" }));
    mockedFetchSpecDraft.mockResolvedValueOnce(
      makeDraft({
        proposed_data: { body_segment: "suv", model_year: "2026", msrp: "575000", engine_capacity_kw: "261.10", powertrain: "bev" },
        missing_fields: [], // an EV correctly has no cc - not "missing"
      }),
    );
    const user = userEvent.setup();

    await pickVariant(user);
    await user.click(screen.getByRole("button", { name: "Fetch Spec Draft" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Add Vehicle" })).toBeInTheDocument(), {
      timeout: 5000,
    });
    const form = screen.getByRole("button", { name: "Create Vehicle" }).closest("form");
    if (!form) throw new Error("vehicle form not found");
    const formScope = within(form);

    expect(formScope.getByLabelText("Powertrain")).toHaveValue("bev");
    expect(formScope.getByLabelText("Engine capacity (cc)")).toBeDisabled();
    expect(formScope.queryByText("Not found - please fill in")).not.toBeInTheDocument();
  });

  // --- Redesign UI-6a: header, list toolbar, phone cards, retry -------------------

  it("has the page header, and shows Active vehicles by default with a count for each filter", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([
      makeVehicle({ id: 1, name: "Camry" }),
      makeVehicle({ id: 2, name: "Old QA Car", is_active: false }),
    ]);
    const user = userEvent.setup();
    render(<AdminFleetPage />);

    expect(screen.getByRole("heading", { level: 1, name: "Fleet management" })).toBeInTheDocument();
    expect(screen.getByText("Cars and brands in the catalog.")).toBeInTheDocument();
    await screen.findByText("Camry");
    const vehiclesRegion = screen.getByRole("region", { name: "Vehicles" });
    expect(within(vehiclesRegion).getByRole("button", { name: "Active (1)" })).toHaveAttribute("aria-pressed", "true");
    expect(within(vehiclesRegion).getByRole("button", { name: "Archived (1)" })).toBeInTheDocument();
    expect(within(vehiclesRegion).getByRole("button", { name: "All (2)" })).toBeInTheDocument();
    expect(screen.queryByText("Old QA Car")).not.toBeInTheDocument();

    await user.click(within(vehiclesRegion).getByRole("button", { name: "All (2)" }));
    await user.type(within(vehiclesRegion).getByRole("searchbox", { name: "Search vehicles" }), "old qa");
    expect(screen.getByText("Old QA Car")).toBeInTheDocument();
    expect(screen.queryByText("Camry")).not.toBeInTheDocument();
  });

  it("puts a row's actions in its menu: Archive in red text, never a solid red button", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([makeVehicle()]);
    const user = userEvent.setup();
    render(<AdminFleetPage />);
    await screen.findByText("Camry");

    expect(screen.queryByRole("button", { name: "Archive" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Actions for Toyota Camry 2.5V" }));
    expect(screen.getAllByRole("menuitem").map((item) => item.textContent)).toEqual(["Edit", "Archive"]);
    expect(screen.getByRole("menuitem", { name: "Archive" })).toHaveClass("text-danger-700");
    expect(document.querySelector('[data-variant="danger"]')).toBeNull();
  });

  it("shows one compact card per vehicle below md, with the same content and menu", async () => {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: false, media: query, addEventListener: vi.fn(), removeEventListener: vi.fn(),
    }));
    try {
      mockedFetchAdminVehicles.mockResolvedValueOnce([makeVehicle({ thumbnail_url: "" })]);
      render(<AdminFleetPage />);

      const list = await screen.findByRole("list", { name: "Vehicles" });
      const card = within(list).getByRole("listitem");
      expect(within(card).getByText("Camry")).toBeInTheDocument();
      expect(within(card).getByText("Sedan · RM 180,000.00")).toBeInTheDocument();
      expect(within(card).getByText("Active")).toBeInTheDocument();
      expect(within(card).getByRole("img", { name: "No photo available for Toyota Camry" })).toBeInTheDocument();
      expect(within(card).getByRole("button", { name: "Actions for Toyota Camry 2.5V" })).toBeInTheDocument();
      expect(screen.getAllByRole("table")).toHaveLength(1); // only the Brands table: the vehicles are cards
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("says the fleet could not load and 'Try again' loads it again", async () => {
    mockedFetchAdminVehicles.mockRejectedValueOnce(new Error("Network Error")).mockResolvedValueOnce([makeVehicle()]);
    const user = userEvent.setup();
    render(<AdminFleetPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load fleet data. Please try again.");
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("Camry")).toBeInTheDocument();
  });

  it("keeps the bulk-import column rules one click away", async () => {
    mockedFetchAdminVehicles.mockResolvedValueOnce([]);
    render(<AdminFleetPage />);

    const help = await screen.findByText(/Required columns:/);
    expect(help.closest("details")?.querySelector("summary")).toHaveTextContent("Columns and file rules");
  });
});
