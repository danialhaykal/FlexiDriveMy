import axios from "axios";
import { apiClient } from "./client";
import type { FinancialProfile, FinancialProfilePayload } from "../types/profile";

// UC003 - apps.profiles.views::FinancialProfileView. A singleton-per-user
// resource (GET/PUT only, no per-row CRUD) - a 404 means "nothing saved
// yet", not an error, so fetchFinancialProfile resolves to null for it
// instead of throwing (every other error still rejects normally).

export async function fetchFinancialProfile(): Promise<FinancialProfile | null> {
  try {
    const { data } = await apiClient.get<FinancialProfile>("/profile/financial/");
    return data;
  } catch (err: unknown) {
    if (axios.isAxiosError(err) && err.response?.status === 404) {
      return null;
    }
    throw err;
  }
}

export async function saveFinancialProfile(
  payload: FinancialProfilePayload,
): Promise<FinancialProfile> {
  const { data } = await apiClient.put<FinancialProfile>("/profile/financial/", {
    ...payload,
    // Optional: a blank income goes over as null (not given), never "".
    monthly_income: payload.monthly_income.trim() === "" ? null : payload.monthly_income,
  });
  return data;
}
