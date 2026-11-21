import { formatCurrency, formatPercent } from "./formatCurrency";
import { formatAdminDate, formatAdminDateTime } from "./formatAdminDate";
import { formatPlainAmount, formatRatioPercent, formatRatioPoints } from "./formatPolicy";

// FX-3 (X13): the audit log in words - display only. The raw resource type and
// the raw before / after data stay in the drawer's "Raw data", and the
// resource-type filter still takes the raw type.

const RESOURCE_NAMES: Record<string, string> = {
  "users.User": "User",
  "profiles.FinancialProfile": "Financial profile",
  "vehicles.Brand": "Brand",
  "vehicles.VehicleModel": "Vehicle",
  "policy.InterestRate": "Interest rate",
  "policy.ResidualValueMatrix": "Residual override",
  "policy.ResidualBaseline": "Residual baseline",
  "policy.ResidualAdjustment": "Residual adjustment",
  "policy.SubscriptionPlan": "Subscription plan",
  "policy.SubscriptionPolicy": "Subscription policy",
  "policy.ContractPenaltyRule": "Contract rule",
  "policy.OperatingCostRate": "Operating cost rate",
  "policy.RoadTaxCcBand": "Road-tax cc band",
  "policy.EvRoadTaxGroup": "EV road-tax group",
  "policy.MCDACriteriaWeight": "Default priority weights",
  "ml.MLTrainingRun": "Training run",
  "ml.ProductionModel": "Production model",
};

// "policy.SomeNewThing" -> "Some new thing" for a type not listed above.
function wordsFromType(resourceType: string): string {
  const model = resourceType.split(".").pop() ?? resourceType;
  const words = model.replace(/([a-z0-9])([A-Z])/g, "$1 $2").toLowerCase();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

// "Interest rate #4", "Vehicle #25", "System error".
export function auditResourceName(resourceType: string, resourceId: string): string {
  if (resourceType === "system.error") return "System error";
  const name = RESOURCE_NAMES[resourceType] ?? wordsFromType(resourceType);
  return resourceId ? `${name} #${resourceId}` : name;
}

// "rate_percent" -> "Rate percent": a field name made readable (the raw data
// keeps the real keys).
export function readableAuditKey(key: string): string {
  const words = key.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

const MONEY_KEYS = new Set([
  "msrp",
  "min_downpayment",
  "fee_monthly",
  "base_amount",
  "excess_mileage_charge_per_km",
]);
const RATIO_KEYS = new Set(["ratio", "residual_value_ratio"]);
const DATE_KEYS = new Set(["effective_from"]);
const DATE_TIME_KEYS = new Set(["created_at", "updated_at", "retired_at", "deployed_at", "timestamp"]);

function isNumeric(value: unknown): boolean {
  return (typeof value === "number" || (typeof value === "string" && value.trim() !== "")) && !Number.isNaN(Number(value));
}

// A value shown the way the policy page shows it: rates "2.80%", ratios
// "78.07%", adjustments "+6.00 pts", money "RM 265,800.00", dates "30 Oct 2026".
export function formatAuditValue(key: string, value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return JSON.stringify(value);
  if (typeof value === "string" && DATE_KEYS.has(key)) return formatAdminDate(value);
  if (typeof value === "string" && DATE_TIME_KEYS.has(key)) return formatAdminDateTime(value);
  if (isNumeric(value)) {
    const text = String(value);
    if (key.endsWith("_percent")) return formatPercent(text);
    if (RATIO_KEYS.has(key)) return formatRatioPercent(text);
    if (key === "delta_points") return formatRatioPoints(text);
    if (MONEY_KEYS.has(key) || key.endsWith("_annual")) return formatCurrency(text);
    if (key === "id" || key === "brand" || key === "vehicle" || key.endsWith("_months")) return text;
    if (typeof value === "number") return value.toLocaleString("en-MY");
    if (text.includes(".")) return formatPlainAmount(text);
  }
  return String(value);
}

// The keys whose value differs between the two sides; nothing when either side
// is missing (a create or an error row has nothing to compare).
export function changedAuditKeys(
  before: Record<string, unknown> | null | undefined,
  after: Record<string, unknown> | null | undefined,
): Set<string> {
  const changed = new Set<string>();
  if (!before || !after) return changed;
  for (const key of new Set([...Object.keys(before), ...Object.keys(after)])) {
    if (JSON.stringify(before[key]) !== JSON.stringify(after[key])) changed.add(key);
  }
  return changed;
}
