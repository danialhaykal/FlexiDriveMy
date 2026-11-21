import { apiClient } from "./client";
import type { MileageBandOption } from "../types/comparisons";

// The one list of mileage bands (value + label showing the band's ceiling in km
// a year) shared by the compare screens and the Financial Profile. Built
// server-side, so the open-ended top band's figure comes from the Subscription
// policy rather than being hard-coded here.
export async function fetchMileageBands(): Promise<MileageBandOption[]> {
  const { data } = await apiClient.get<MileageBandOption[]>("/comparisons/mileage-bands/");
  return data;
}
