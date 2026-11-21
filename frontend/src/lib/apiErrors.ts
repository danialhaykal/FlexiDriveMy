// QA audit M13: every 400-handling block used to hand-check a hardcoded
// allowlist of field names (RecommendationPanel only checked
// `.priorities`/`.downpayment`/`.detail`, so a 400 on monthly_income or
// max_dsr_percent fell through to a generic "please try again" even
// though DRF already returned a specific message for it). This is the
// one shared parser every 400-handling block should use instead -
// it looks across WHATEVER fields DRF's response body actually has, not
// a fixed list, so a new/renamed serializer field is covered
// automatically.
//
// DRF's own two error shapes:
//   - a field-level validation error: { "<field_name>": ["message", ...], ... }
//   - a non-field error (e.g. a raised ValidationError/ a permission
//     error): { "detail": "message" }
// `detail` is checked LAST, not first - a field-level message is always
// more specific/actionable than a generic `detail` string, and the two
// are not mutually exclusive in general, so field errors take priority
// when both happen to be present.
export function parseApiErrorMessage(data: unknown): string | null {
  if (!data || typeof data !== "object") return null;
  const record = data as Record<string, unknown>;

  for (const [key, value] of Object.entries(record)) {
    if (key === "detail") continue;
    if (Array.isArray(value) && typeof value[0] === "string") {
      return value[0];
    }
    if (typeof value === "string") {
      return value;
    }
    // A nested serializer's errors, e.g. a saved scenario's
    // { inputs: { downpayment: ["..."] } } or { inputs: { scoring: { priorities: [...] } } }.
    if (value && typeof value === "object" && !Array.isArray(value)) {
      const nested = parseApiErrorMessage(value);
      if (nested) return nested;
    }
  }

  return typeof record.detail === "string" ? record.detail : null;
}

// Batch 6A: the admin CRUD forms (UC010/UC011) need PER-FIELD messages,
// not just the single "most relevant" one parseApiErrorMessage above
// picks - their alternate flows require showing the server's exact
// verbatim copy next to the offending field while PRESERVING every
// other field's already-entered value, so every field with an error
// needs its own message, not just the first.
export function parseApiFieldErrors(data: unknown): Record<string, string> {
  const fieldErrors: Record<string, string> = {};
  if (!data || typeof data !== "object") return fieldErrors;
  const record = data as Record<string, unknown>;

  for (const [key, value] of Object.entries(record)) {
    if (key === "detail") continue;
    if (Array.isArray(value) && typeof value[0] === "string") {
      fieldErrors[key] = value[0];
    } else if (typeof value === "string") {
      fieldErrors[key] = value;
    }
  }

  return fieldErrors;
}

// FX-2 (item 1, Run 4 R4-P4-02): a page that loads one record must tell a
// missing record apart from a server it cannot reach. Only a real 404 is
// "not found"; no response at all, or a 5xx, is the server being unreachable.
export const SERVER_UNREACHABLE_MESSAGE = "We can't reach the server right now. Check your connection and try again.";

export function isNotFoundError(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const response = (error as { response?: { status?: number } }).response;
  return response?.status === 404;
}

