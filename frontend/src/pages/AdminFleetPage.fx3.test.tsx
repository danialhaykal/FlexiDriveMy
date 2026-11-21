import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  AdminFleetPage,
  BULK_IMPORT_OPTIONAL_COLUMNS,
  BULK_IMPORT_REQUIRED_COLUMNS,
  BULK_IMPORT_TEMPLATE_FILENAME,
  TIER_LEGEND,
  bulkImportTemplateCsv,
  tierLabel,
} from "./AdminFleetPage";
import { fetchAdminBrands, fetchAdminVehicles } from "../api/adminFleet";
import type { AdminBrand, AdminVehicle } from "../types/adminFleet";

// FX-3: the brand tier legend (X13), the brand filter by list status (X6) and the bulk-import CSV template.

vi.mock("../api/adminFleet", () => ({
  fetchAdminVehicles: vi.fn(), fetchAdminBrands: vi.fn(), createVehicle: vi.fn(), updateVehicle: vi.fn(),
  archiveVehicle: vi.fn(), bulkImportVehicles: vi.fn(), createBrand: vi.fn(), archiveBrand: vi.fn(),
  fetchResearchModels: vi.fn(), fetchResearchVariants: vi.fn(), createSpecDraft: vi.fn(), fetchSpecDraft: vi.fn(),
  patchSpecDraft: vi.fn(), fetchBrandArchiveImpact: vi.fn(), fetchVehicleArchiveImpact: vi.fn(),
  unarchiveBrand: vi.fn(), unarchiveVehicle: vi.fn(),
}));

function makeBrand(overrides: Partial<AdminBrand>): AdminBrand {
  return {
    id: 1, name: "BMW", tier_code: "2", is_active: true, created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z", ...overrides,
  };
}

const BRANDS = [
  makeBrand({ id: 1, name: "BMW", tier_code: "2" }),
  makeBrand({ id: 2, name: "QA Archived Motors", tier_code: "", is_active: false }),
];

const VEHICLE: AdminVehicle = {
  id: 5, brand: 1, brand_name: "BMW", name: "320i", trim: "Sport", body_segment: "sedan", model_year: 2025,
  msrp: "267800.00", min_downpayment: "26780.00", engine_capacity_kw: "135.00", powertrain: "petrol",
  engine_capacity_cc: 1998, spec_complete: true, thumbnail_url: "", is_active: true,
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(fetchAdminBrands).mockResolvedValue(BRANDS);
  vi.mocked(fetchAdminVehicles).mockResolvedValue([VEHICLE]);
});

function brandFilterOptions(): string[] {
  const select = screen.getByLabelText("Filter by brand") as HTMLSelectElement;
  return Array.from(select.options).map((option) => option.textContent ?? "");
}

describe("brand price tier", () => {
  it("labels a tier as 'Tier N' and an empty one as not set", () => {
    expect(tierLabel("1")).toBe("Tier 1");
    expect(tierLabel("")).toBe("Not set");
    expect(TIER_LEGEND).toMatch(/Tier 1 has the highest resale values, Tier 5 the lowest/);
  });

  it("shows Tier N in the brands table with an info tooltip explaining the code", async () => {
    const user = userEvent.setup();
    render(<AdminFleetPage />);
    const region = await screen.findByRole("region", { name: "Brands" });

    expect(await within(region).findByText("Tier 2")).toBeInTheDocument();
    const tip = within(region).getByRole("button", { name: "About price tiers" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    await user.hover(tip);
    expect(screen.getByRole("tooltip")).toHaveTextContent(TIER_LEGEND);
    expect(tip).toHaveAttribute("aria-describedby", screen.getByRole("tooltip").id);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
});

describe("brand filter (X6)", () => {
  it("lists only active brands under Active, and archived ones marked under Archived / All", async () => {
    const user = userEvent.setup();
    render(<AdminFleetPage />);
    const vehicles = await screen.findByRole("region", { name: "Vehicles" });
    await within(vehicles).findByText("320i");

    expect(brandFilterOptions()).toEqual(["All brands", "BMW"]);
    await user.click(within(vehicles).getByRole("button", { name: /^All \(/ }));
    expect(brandFilterOptions()).toEqual(["All brands", "BMW", "QA Archived Motors (archived)"]);
    await user.click(within(vehicles).getByRole("button", { name: /^Archived \(/ }));
    expect(brandFilterOptions()).toEqual(["All brands", "BMW", "QA Archived Motors (archived)"]);
  });

  it("clears an archived brand choice when going back to Active", async () => {
    const user = userEvent.setup();
    render(<AdminFleetPage />);
    const vehicles = await screen.findByRole("region", { name: "Vehicles" });
    await within(vehicles).findByText("320i");

    await user.click(within(vehicles).getByRole("button", { name: /^All \(/ }));
    await user.selectOptions(screen.getByLabelText("Filter by brand"), "2");
    await user.click(within(vehicles).getByRole("button", { name: /^Active \(/ }));

    expect((screen.getByLabelText("Filter by brand") as HTMLSelectElement).value).toBe("");
    expect(within(vehicles).getByText("320i")).toBeInTheDocument();
  });
});

describe("bulk import CSV template", () => {
  it("is a header-only CSV of exactly the columns the help text lists", async () => {
    const columns = [...BULK_IMPORT_REQUIRED_COLUMNS, ...BULK_IMPORT_OPTIONAL_COLUMNS];
    expect(bulkImportTemplateCsv()).toBe(`${columns.join(",")}\r\n`);
    expect(BULK_IMPORT_REQUIRED_COLUMNS).toEqual(["brand", "name", "trim", "body_segment", "msrp", "engine_capacity_kw", "powertrain"]);

    render(<AdminFleetPage />);
    const help = await screen.findByText(/Required columns:/);
    for (const column of columns) expect(help).toHaveTextContent(column);
    expect(help).toHaveTextContent("engine_capacity_kw (power output in kW)");
  });

  it("downloads the template from the browser, with no request", async () => {
    const createObjectURL = vi.fn(() => "blob:template");
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    const clicked: { download: string; href: string }[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      clicked.push({ download: this.download, href: this.href });
    });
    const user = userEvent.setup();
    render(<AdminFleetPage />);

    await user.click(await screen.findByRole("button", { name: "Download CSV template" }));

    expect(clicked).toEqual([{ download: BULK_IMPORT_TEMPLATE_FILENAME, href: "blob:template" }]);
    const blob = (createObjectURL.mock.calls[0] as unknown as [Blob])[0];
    expect(await blob.text()).toBe(bulkImportTemplateCsv());
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:template");
    expect(fetchAdminVehicles).toHaveBeenCalledTimes(1); // the page's own load only
    click.mockRestore();
  });
});
