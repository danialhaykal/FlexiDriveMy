export type BodySegment =
  | "sedan"
  | "hatchback"
  | "suv"
  | "mpv"
  | "pickup"
  | "coupe"
  | "crossover"
  | "van";

export const BODY_SEGMENT_OPTIONS: { value: BodySegment; label: string }[] = [
  { value: "sedan", label: "Sedan" },
  { value: "hatchback", label: "Hatchback" },
  { value: "suv", label: "SUV" },
  { value: "mpv", label: "MPV" },
  { value: "pickup", label: "Pickup Truck" },
  { value: "coupe", label: "Coupe" },
  { value: "crossover", label: "Crossover" },
  { value: "van", label: "Van" },
];

// Mirrors apps.vehicles.models.Powertrain. "" is a legacy row entered
// before powertrain existed (spec_complete is then false).
export type Powertrain = "petrol" | "diesel" | "mild_hybrid" | "hybrid" | "phev" | "bev";

export const POWERTRAIN_OPTIONS: { value: Powertrain; label: string }[] = [
  { value: "petrol", label: "Petrol" },
  { value: "diesel", label: "Diesel" },
  { value: "mild_hybrid", label: "Mild hybrid (MHEV)" },
  { value: "hybrid", label: "Hybrid (HEV)" },
  { value: "phev", label: "Plug-in hybrid (PHEV)" },
  { value: "bev", label: "Battery electric (BEV)" },
];

export interface Brand {
  id: number;
  name: string;
  tier_code: string;
  is_active: boolean;
}

export interface Vehicle {
  id: number;
  brand: number;
  brand_name: string;
  name: string;
  trim: string;
  body_segment: BodySegment;
  model_year: number | null;
  msrp: string;
  // 10% of msrp, rounded up to the cent - computed server-side (C6:
  // apps.common.constants.minimum_downpayment_for) so the frontend never
  // derives a monetary figure itself. Use for defaulting/validating a
  // downpayment input by comparison only, never arithmetic.
  min_downpayment: string;
  // Legacy name: POWER OUTPUT in kW (not engine displacement) - the ML
  // feature and API key keep it. Displacement is engine_capacity_cc.
  engine_capacity_kw: string;
  powertrain: Powertrain | "";
  // Server-built plain name ("mild hybrid", "electric"), the same words the
  // running-cost and residual lines use; "" when no powertrain is set.
  powertrain_phrase?: string;
  // Engine displacement; null for a BEV (and for legacy rows with no value).
  engine_capacity_cc: number | null;
  // Server-computed: false for a row that still needs powertrain/cc.
  spec_complete: boolean;
  thumbnail_url: string;
  is_active: boolean;
}

export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface CatalogFilterState {
  brand: string;
  bodySegment: string;
  minPrice: string;
  maxPrice: string;
  search: string;
}

export const EMPTY_CATALOG_FILTERS: CatalogFilterState = {
  brand: "",
  bodySegment: "",
  minPrice: "",
  maxPrice: "",
  search: "",
};
