import { apiClient } from "./client";
import type { ScoringParams, ScoringResult } from "../types/scoring";
import type { DsrSimulatorParams, DsrSimulatorResult } from "../types/dsrSimulator";

// GET /api/scoring/ (F007 / UC007) - server normalizes the quiz weights
// and computes MCDA suitability scores, DSR%, and ranking; this call
// only collects quiz inputs and returns exactly what the API responds
// with. A 400 can be an incomplete-quiz error (`.priorities`), a
// standard field-validation error (e.g. `.downpayment`), or a
// missing-config error (`.detail`) - callers should check them in that
// order, per the API contract.
export async function fetchScoring(params: ScoringParams): Promise<ScoringResult> {
  const { data } = await apiClient.get<ScoringResult>("/scoring/", {
    params: {
      vehicle: params.vehicle,
      tenure_months: params.tenureMonths,
      mileage_band: params.mileageBand,
      downpayment: params.downpayment,
      upfront_cash_preservation: params.upfrontCashPreservation,
      maintenance_protection: params.maintenanceProtection,
      ownership_equity: params.ownershipEquity,
      monthly_income: params.monthlyIncome,
      max_dsr_percent: params.maxDsrPercent,
    },
  });
  return data;
}

// GET /api/scoring/dsr-simulator/ (Sprint 11) - a standalone Affordability
// / DSR Simulator, separate from F007's own recommendation flow above. A
// 400 can be a standard field-validation error (e.g. `.downpayment`) or a
// missing-config error (`.detail`), same contract as fetchScoring.
export async function fetchDsrSimulator(params: DsrSimulatorParams): Promise<DsrSimulatorResult> {
  const { data } = await apiClient.get<DsrSimulatorResult>("/scoring/dsr-simulator/", {
    params: {
      vehicle: params.vehicle,
      tenure_months: params.tenureMonths,
      mileage_band: params.mileageBand,
      downpayment: params.downpayment,
      monthly_income: params.monthlyIncome,
      max_dsr_percent: params.maxDsrPercent,
      existing_monthly_commitments: params.existingMonthlyCommitments,
    },
  });
  return data;
}
