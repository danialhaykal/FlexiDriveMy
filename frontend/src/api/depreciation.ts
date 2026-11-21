import { apiClient } from "./client";
import type { TcoParams, TcoReport } from "../types/depreciation";
import type { TotalLossSandboxParams, TotalLossSandboxResult } from "../types/totalLossSandbox";

// GET /api/depreciation/tco/ (F006 / UC006) - server computes the
// 60-month resale forecast and TCO summary; this call only collects
// inputs and returns exactly what the API responds with. A 400 means
// missing interest-rate/operating-cost-band config for this vehicle -
// callers should surface `error.response?.data?.detail`.
export async function fetchTcoReport(params: TcoParams): Promise<TcoReport> {
  const { data } = await apiClient.get<TcoReport>("/depreciation/tco/", {
    params: {
      vehicle: params.vehicle,
      tenure_months: params.tenureMonths,
      mileage_band: params.mileageBand,
      downpayment: params.downpayment,
    },
  });
  return data;
}

// GET /api/depreciation/total-loss-sandbox/ (Sprint 12) - an illustrative
// "what if this vehicle were written off in month M" sandbox, separate
// from F006's own TCO report above. A 400 can be a standard
// field-validation error (e.g. `.downpayment`, `.loss_month`) or a
// missing-config error (`.detail`), same contract as fetchTcoReport.
export async function fetchTotalLossSandbox(
  params: TotalLossSandboxParams,
): Promise<TotalLossSandboxResult> {
  const { data } = await apiClient.get<TotalLossSandboxResult>("/depreciation/total-loss-sandbox/", {
    params: {
      vehicle: params.vehicle,
      tenure_months: params.tenureMonths,
      mileage_band: params.mileageBand,
      downpayment: params.downpayment,
      loss_month: params.lossMonth,
      excess_amount: params.excessAmount,
    },
  });
  return data;
}
