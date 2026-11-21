import type { PaginatedResponse } from "./catalog";

// Batch 6A - mirrors apps/audit/serializers.py::AuditLogSerializer and
// apps/audit/models.py::AuditActionCategory exactly.

export type AuditActionCategory = "create" | "update" | "archive" | "bulk_import" | "runtime_error";

export const AUDIT_ACTION_OPTIONS: { value: AuditActionCategory; label: string }[] = [
  { value: "create", label: "Create" },
  { value: "update", label: "Update" },
  { value: "archive", label: "Archive" },
  { value: "bulk_import", label: "Bulk Import" },
  // Run 1 fix batch 4: unhandled system errors (resource "system.error";
  // after_data holds the error type, a short message, path, method, status).
  { value: "runtime_error", label: "Runtime error" },
];

export interface AuditLog {
  id: number;
  actor_id: number | null;
  actor_email: string;
  timestamp: string;
  action: AuditActionCategory;
  resource_type: string;
  resource_id: string;
  ip_address: string | null;
  before_data: Record<string, unknown> | null;
  after_data: Record<string, unknown> | null;
}

export type AuditLogListResponse = PaginatedResponse<AuditLog>;

export interface AuditLogFilters {
  // The user's id - still accepted by the API for callers that have one; the
  // page itself filters by email (actor_email) instead.
  actor?: string;
  // Case-insensitive exact match on the email recorded on each log row.
  actor_email?: string;
  action?: AuditActionCategory | "";
  resource_type?: string;
  timestamp_from?: string;
  timestamp_to?: string;
}
