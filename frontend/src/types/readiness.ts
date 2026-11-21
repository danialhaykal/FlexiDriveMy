// GET /api/admin/vehicle-readiness/ - mirrors apps/vehicles/readiness.py. Every
// check is computed server-side from the same code the screens use; this page
// only displays it.

// "info" (run 2 fix batch 3) only says how something is done (e.g. which resale
// forecast a car gets); it is never counted and never blocks.
export type ReadinessCheckStatus = "ok" | "missing" | "warning" | "info";
export type ReadinessStatus = "ready" | "needs_attention";

export interface ReadinessCheck {
  key: string;
  label: string;
  status: ReadinessCheckStatus;
  detail: string;
}

export interface VehicleReadiness {
  vehicle_id: number;
  label: string;
  brand_name: string;
  status: ReadinessStatus;
  missing_count: number;
  warning_count: number;
  checks: ReadinessCheck[];
}

export interface VehicleReadinessResponse {
  results: VehicleReadiness[];
}
