import type { BodySegment, PaginatedResponse, Powertrain } from "./catalog";

// Batch 6A - mirrors apps/vehicles/serializers.py::BrandSerializer /
// VehicleModelSerializer exactly for the admin CRUD surface (UC010).
// The existing `Brand`/`Vehicle` types in ./catalog are the PUBLIC
// catalog shape (CatalogVehicleViewSet) and omit created_at/updated_at,
// which the admin endpoints do return - kept as separate types rather
// than widening the public ones.

export interface AdminBrand {
  id: number;
  name: string;
  tier_code: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface AdminVehicle {
  id: number;
  brand: number;
  brand_name: string;
  name: string;
  trim: string;
  body_segment: BodySegment;
  model_year: number | null;
  msrp: string;
  min_downpayment: string;
  // Power output in kW (legacy field name - see ./catalog's Vehicle).
  engine_capacity_kw: string;
  powertrain: Powertrain | "";
  engine_capacity_cc: number | null;
  // JPJ registration class for the cc road-tax table. Always stored by the
  // server (from the body type when left blank); undefined only in an old
  // response.
  road_tax_class?: RoadTaxClass;
  // False when set differently from the body type's usual class.
  road_tax_class_is_default?: boolean;
  spec_complete: boolean;
  thumbnail_url: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export type RoadTaxClass = "saloon" | "non_saloon";

// "" = use the body type's usual class (the server fills it in).
export const ROAD_TAX_CLASS_OPTIONS: { value: RoadTaxClass | ""; label: string }[] = [
  { value: "", label: "Usual for the body type" },
  { value: "saloon", label: "Saloon" },
  { value: "non_saloon", label: "Non-saloon" },
];
export const ROAD_TAX_CLASS_HELP_TEXT =
  "Use the class on the car's registration card (VOC). Body type is only the default.";

export type AdminBrandListResponse = PaginatedResponse<AdminBrand>;
export type AdminVehicleListResponse = PaginatedResponse<AdminVehicle>;

export interface BrandWritePayload {
  name: string;
  tier_code: string;
}

export interface VehicleWritePayload {
  brand: number | "";
  name: string;
  trim: string;
  body_segment: BodySegment | "";
  model_year: number | "";
  msrp: string;
  // Power output in kW (legacy field name).
  engine_capacity_kw: string;
  powertrain: Powertrain | "";
  // "" while blank, and always for a BEV (which has no engine capacity).
  engine_capacity_cc: number | "";
  // "" = the body type's usual class, filled in by the server.
  road_tax_class: RoadTaxClass | "";
  thumbnail_url: string;
}

// What createVehicle/updateVehicle actually send: a blank cc or model year
// goes over the wire as null (JSON "" is not an integer).
export type VehicleApiPayload = Omit<VehicleWritePayload, "engine_capacity_cc" | "model_year"> & {
  engine_capacity_cc: number | null;
  model_year: number | null;
  // Run 1 fix batch 5 (G7): on an edit, the updated_at the form was loaded
  // with - a 409 comes back if someone else saved the row since.
  updated_at?: string;
};

// Mirrors apps.vehicles.archiving.CascadePlan.as_dict(): what archiving
// (or reactivating) a brand/vehicle also changes. Brand impacts carry all
// five groups; vehicle impacts only subscription_plans.
export type ArchiveImpactGroup =
  | "vehicles"
  | "interest_rates"
  | "residual_value_rows"
  | "penalty_rules"
  | "subscription_plans";

export interface ArchiveSkippedRow {
  resource_type: string;
  id: number;
  label: string;
  reason: string;
}

export interface ArchiveImpact {
  action: "archive" | "restore";
  counts: Partial<Record<ArchiveImpactGroup, number>>;
  skipped: ArchiveSkippedRow[];
}

export type UnarchiveBrandResponse = AdminBrand & { cascade: ArchiveImpact };
export type UnarchiveVehicleResponse = AdminVehicle & { cascade: ArchiveImpact };

export interface BulkImportRowError {
  row: number;
  errors: Record<string, string[] | string>;
}

export interface BulkImportResponse {
  total_rows: number;
  created_count: number;
  error_count: number;
  errors: BulkImportRowError[];
  created: AdminVehicle[];
}
