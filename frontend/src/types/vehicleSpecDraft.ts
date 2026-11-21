// F010 optional stretch goal - UC010's "Fetch Spec Draft" admin assist.
// Mirrors apps.vehicles.serializers.VehicleSpecDraftSerializer /
// VehicleSpecDraftCreateSerializer and the catalog-models/catalog-variants
// actions on apps.vehicles.views.VehicleSpecDraftViewSet exactly.

export type VehicleSpecDraftStatus = "pending" | "ready" | "not_found" | "approved" | "failed";

// Whichever of these four were actually extracted - a key's ABSENCE (not
// an empty string) means that field is instead named in missing_fields.
// Numeric values arrive as decimal strings, same convention as every
// other currency/measurement field in this app (the project spec: never derive/
// recompute these client-side, only display and pre-fill the form with
// them exactly as returned).
export interface VehicleSpecDraftProposedData {
  body_segment?: string;
  model_year?: string;
  msrp?: string;
  // Power output in kW (legacy field name).
  engine_capacity_kw?: string;
  // Absent for a BEV (it has no cc and it is not "missing" either), and
  // absent from either when the page doesn't say clearly - never guessed.
  powertrain?: string;
  engine_capacity_cc?: string;
}

export interface VehicleSpecDraft {
  id: number;
  brand: number;
  brand_name: string;
  model_name_query: string;
  trim_query: string;
  status: VehicleSpecDraftStatus;
  source_url: string;
  proposed_data: VehicleSpecDraftProposedData;
  missing_fields: string[];
  fetched_at: string | null;
  // Short reason when status is "failed"; "" otherwise.
  error_message: string;
  approved_vehicle: number | null;
  requested_by: number | null;
  created_at: string;
  updated_at: string;
}

// source_url must be a paultan.org buyer's-guide VARIANT page (the server
// rejects anything else - SSRF guard). model_name_query/trim_query are
// display text that also pre-fill the form's Name/Trim.
export interface VehicleSpecDraftCreatePayload {
  brand: number;
  source_url: string;
  model_name_query: string;
  trim_query: string;
}

// The only write path after creation - fire-and-forget traceability only
// (see VehicleSpecDraft's own backend docstring), never required for the
// admin's real Add Vehicle save to succeed.
export interface VehicleSpecDraftApprovalPayload {
  status: "approved";
  approved_vehicle: number;
}

// One model card from paultan's /research/<brand>/ page.
export interface ResearchModel {
  name: string;
  url: string;
  price_text: string;
  on_sale: boolean;
}

export interface ResearchModelsResponse {
  brand_slug: string;
  models: ResearchModel[];
  message?: string;
}

// One variant card from paultan's /research/<brand>/<model>/ page. Already
// sorted server-side: on-sale first, newest year first, then cheapest.
export interface ResearchVariant {
  name: string;
  url: string;
  generation: string;
  year: number;
  msrp: string | null;
  power_hp: number | null;
  on_sale: boolean;
}

export interface ResearchVariantsResponse {
  variants: ResearchVariant[];
  message?: string;
}
