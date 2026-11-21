import { apiClient } from "./client";
import { fetchAllPages } from "./allPages";
import type { FullList } from "./allPages";
import type {
  ContractPenaltyRule,
  InterestRate,
  MCDACriteriaWeight,
  OperatingCostsResponse,
  ResidualEstimatesResponse,
  ResidualValueMatrixEntry,
  SubscriptionEstimatesResponse,
  SubscriptionPlan,
} from "../types/policy";

// Batch 6A, UC011 - admin-only policy config CRUD (apps.policy.views).
// Every list function passes include_archived=true: UC011's admin page
// shows archived rows alongside active ones (same AuditedModelViewSet
// convention as UC010's fleet list), the archive action is a DELETE
// (soft-delete), and every create() leaves the "already has an active
// one" 400 to the server's own serializer-level guard rather than
// re-checking it client-side first (the project spec: Python is the sole
// validation/arithmetic authority).

// Run 1 fix batch 5 (G7): an edit sends back the updated_at it loaded the row
// with; the server answers 409 if someone else saved the row since.
type WithLoadedVersion<T> = T & { updated_at?: string };

// Run 3 fix batch 4 (F-17): every list below loads all of its pages, not just
// the first 25 rows (api/allPages.ts).

export async function fetchInterestRates(): Promise<FullList<InterestRate>> {
  return fetchAllPages<InterestRate>("/policy/interest-rates/", { include_archived: true });
}

export async function createInterestRate(payload: {
  brand: number | "";
  rate_percent: string;
}): Promise<InterestRate> {
  const { data } = await apiClient.post<InterestRate>("/policy/interest-rates/", payload);
  return data;
}

export async function updateInterestRate(
  id: number,
  payload: WithLoadedVersion<{ brand: number | ""; rate_percent: string }>,
): Promise<InterestRate> {
  const { data } = await apiClient.put<InterestRate>(`/policy/interest-rates/${id}/`, payload);
  return data;
}

export async function archiveInterestRate(id: number): Promise<void> {
  await apiClient.delete(`/policy/interest-rates/${id}/`);
}

export async function fetchResidualValueMatrix(): Promise<FullList<ResidualValueMatrixEntry>> {
  return fetchAllPages<ResidualValueMatrixEntry>("/policy/residual-value-matrix/", { include_archived: true });
}

export interface ResidualValueMatrixWritePayload {
  brand: number | "";
  tenure_months: number | "";
  mileage_band: string;
  residual_value_ratio: string;
}

export async function createResidualValueMatrixEntry(
  payload: ResidualValueMatrixWritePayload,
): Promise<ResidualValueMatrixEntry> {
  const { data } = await apiClient.post<ResidualValueMatrixEntry>(
    "/policy/residual-value-matrix/",
    payload,
  );
  return data;
}

export async function updateResidualValueMatrixEntry(
  id: number,
  payload: WithLoadedVersion<ResidualValueMatrixWritePayload>,
): Promise<ResidualValueMatrixEntry> {
  const { data } = await apiClient.put<ResidualValueMatrixEntry>(
    `/policy/residual-value-matrix/${id}/`,
    payload,
  );
  return data;
}

export async function archiveResidualValueMatrixEntry(id: number): Promise<void> {
  await apiClient.delete(`/policy/residual-value-matrix/${id}/`);
}

export async function fetchMCDAWeights(): Promise<MCDACriteriaWeight[]> {
  const { data } = await apiClient.get<MCDACriteriaWeight[]>("/policy/mcda-weights/");
  return data;
}

export async function updateMCDAWeights(
  weights: { criterion: string; default_weight: string }[],
): Promise<MCDACriteriaWeight[]> {
  const { data } = await apiClient.put<MCDACriteriaWeight[]>("/policy/mcda-weights/", { weights });
  return data;
}

// Read-only: road tax / insurance / maintenance rate tables, with source and
// effective date, for the Policy Configuration "Operating Costs" tab.
export async function fetchOperatingCosts(): Promise<OperatingCostsResponse> {
  const { data } = await apiClient.get<OperatingCostsResponse>("/policy/operating-costs/");
  return data;
}

// Read-only: the residual estimator's baseline grid and brand/powertrain
// adjustments, with their planning-estimate source notes, for the Policy
// Configuration "Residual Estimates" tab.
export async function fetchResidualEstimates(): Promise<ResidualEstimatesResponse> {
  const { data } = await apiClient.get<ResidualEstimatesResponse>("/policy/residual-estimates/");
  return data;
}

// Read-only: the SubscriptionPolicy assumptions (tenure range, funding rate,
// margin, deposit, very-high-band km), for the "Subscription Estimates" tab.
export async function fetchSubscriptionEstimates(): Promise<SubscriptionEstimatesResponse> {
  const { data } = await apiClient.get<SubscriptionEstimatesResponse>("/policy/subscription-estimates/");
  return data;
}

export async function fetchSubscriptionPlans(): Promise<FullList<SubscriptionPlan>> {
  return fetchAllPages<SubscriptionPlan>("/policy/subscription-plans/", { include_archived: true });
}

export interface SubscriptionPlanWritePayload {
  vehicle: number | "";
  // Only the monthly fee is asked for - road tax, insurance and maintenance are
  // derived from the vehicle's own specs (apps.policy.operating_costs).
  fee_monthly: string;
}

export async function createSubscriptionPlan(
  payload: SubscriptionPlanWritePayload,
): Promise<SubscriptionPlan> {
  const { data } = await apiClient.post<SubscriptionPlan>("/policy/subscription-plans/", payload);
  return data;
}

export async function updateSubscriptionPlan(
  id: number,
  payload: WithLoadedVersion<SubscriptionPlanWritePayload>,
): Promise<SubscriptionPlan> {
  const { data } = await apiClient.put<SubscriptionPlan>(`/policy/subscription-plans/${id}/`, payload);
  return data;
}

export async function archiveSubscriptionPlan(id: number): Promise<void> {
  await apiClient.delete(`/policy/subscription-plans/${id}/`);
}

export async function fetchContractPenaltyRules(): Promise<FullList<ContractPenaltyRule>> {
  return fetchAllPages<ContractPenaltyRule>("/policy/contract-penalty-rules/", { include_archived: true });
}

export interface ContractPenaltyRuleWritePayload {
  // null = the default rule (every brand without its own row uses it).
  brand: number | null;
  excess_mileage_charge_per_km: string;
  // "" = leave empty (a brand rule then uses the default's months).
  early_termination_months: string;
  wear_tear_tolerance_description: string;
}

// An empty months box means "inherit the default rule's", sent as JSON null.
function contractRuleWire(payload: ContractPenaltyRuleWritePayload) {
  return {
    ...payload,
    early_termination_months: payload.early_termination_months === "" ? null : payload.early_termination_months,
  };
}

export async function createContractPenaltyRule(
  payload: ContractPenaltyRuleWritePayload,
): Promise<ContractPenaltyRule> {
  const { data } = await apiClient.post<ContractPenaltyRule>(
    "/policy/contract-penalty-rules/",
    contractRuleWire(payload),
  );
  return data;
}

export async function updateContractPenaltyRule(
  id: number,
  payload: WithLoadedVersion<ContractPenaltyRuleWritePayload>,
): Promise<ContractPenaltyRule> {
  const { data } = await apiClient.put<ContractPenaltyRule>(
    `/policy/contract-penalty-rules/${id}/`,
    contractRuleWire(payload),
  );
  return data;
}

export async function archiveContractPenaltyRule(id: number): Promise<void> {
  await apiClient.delete(`/policy/contract-penalty-rules/${id}/`);
}
