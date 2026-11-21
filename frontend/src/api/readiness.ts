import { apiClient } from "./client";
import type { VehicleReadiness, VehicleReadinessResponse } from "../types/readiness";

// Admin only, read-only: whether the app can fully price each active vehicle.
export async function fetchVehicleReadiness(): Promise<VehicleReadiness[]> {
  const { data } = await apiClient.get<VehicleReadinessResponse>("/admin/vehicle-readiness/");
  return data.results;
}
