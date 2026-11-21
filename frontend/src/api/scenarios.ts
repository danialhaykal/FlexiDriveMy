import { apiClient } from "./client";
import type { Scenario, ScenarioInputs } from "../types/scenarios";

// /api/scenarios/ (F009 / UC009) - a standard REST resource scoped to
// the current user server-side. Saving sends the INPUTS on screen and the
// server calculates the snapshot with the same services as the live
// screens; retrieving returns that snapshot unchanged.

interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

// The list endpoint uses DRF's default PageNumberPagination - a bare
// Scenario[] was never the real response shape, it just happened to look
// like one until a user had enough saved scenarios to trigger a second
// page. Follows `next` until every page has been fetched, so a user with
// 26+ scenarios still sees all of them on one call.
export async function listScenarios(): Promise<Scenario[]> {
  const results: Scenario[] = [];
  let url: string | null = "/scenarios/";
  while (url) {
    const { data }: { data: PaginatedResponse<Scenario> } = await apiClient.get<PaginatedResponse<Scenario>>(url);
    results.push(...data.results);
    url = data.next;
  }
  return results;
}

export async function getScenario(id: number | string): Promise<Scenario> {
  const { data } = await apiClient.get<Scenario>(`/scenarios/${id}/`);
  return data;
}

interface SaveScenarioParams {
  title: string;
  vehicle: number;
  // Inputs only - the server calculates and stores the figures.
  inputs: ScenarioInputs;
  // Resubmit with overwrite: true to replace an existing scenario after
  // a 409 duplicate-title response (UC009's alternate flow).
  overwrite?: boolean;
}

export async function saveScenario(params: SaveScenarioParams): Promise<Scenario> {
  const { data } = await apiClient.post<Scenario>("/scenarios/", {
    title: params.title,
    vehicle: params.vehicle,
    inputs: params.inputs,
    overwrite: params.overwrite ?? false,
  });
  return data;
}

export async function deleteScenario(id: number): Promise<void> {
  await apiClient.delete(`/scenarios/${id}/`);
}
