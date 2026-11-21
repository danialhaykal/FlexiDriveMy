import { apiClient } from "./client";
import type { ComparisonParams, ComparisonResult } from "../types/comparisons";
import type { ArenaParams, ArenaResult } from "../types/arena";

// GET /api/comparisons/ (F005 / UC005) - server computes all three
// pathways; this call only collects inputs and returns exactly what the
// API responds with. A 400 means the alternate flow (missing/null
// interest-rate or residual-ratio config for this brand/tenure/mileage
// combination) - callers should surface `error.response?.data?.detail`.
export async function fetchComparison(params: ComparisonParams): Promise<ComparisonResult> {
  const { data } = await apiClient.get<ComparisonResult>("/comparisons/", {
    params: {
      vehicle: params.vehicle,
      tenure_months: params.tenureMonths,
      mileage_band: params.mileageBand,
      downpayment: params.downpayment,
    },
  });
  return data;
}

// GET /api/comparisons/arena/ (Sprint 10) - runs the same F005/F006
// calculations as fetchComparison, once per selected vehicle (2-3), plus
// derived winner badges. A per-vehicle config problem is NOT a request
// failure - it's a 200 with that vehicle's own `ok: false` entry; see
// ArenaEntry.
//
// paramsSerializer here is deliberate and specific to this one call:
// axios's default array serialization produces `vehicles[]=1&vehicles[]=2`
// (verified directly against the installed axios version), but DRF's
// PrimaryKeyRelatedField(many=True) reads a repeated-key query param via
// QueryDict.getlist("vehicles") - it needs `vehicles=1&vehicles=2`
// (`indexes: null` on the serializer produces exactly that), not the
// bracketed form. Scoped to this request only, not set globally on
// apiClient, since no other endpoint here uses an array query param.
export async function fetchArena(params: ArenaParams): Promise<ArenaResult> {
  const { data } = await apiClient.get<ArenaResult>("/comparisons/arena/", {
    params: {
      vehicles: params.vehicles,
      tenure_months: params.tenureMonths,
      mileage_band: params.mileageBand,
      downpayment: params.downpayment,
    },
    paramsSerializer: { indexes: null },
  });
  return data;
}
