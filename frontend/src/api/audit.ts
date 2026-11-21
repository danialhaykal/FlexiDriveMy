import { apiClient } from "./client";
import type { AuditLogFilters, AuditLogListResponse } from "../types/audit";

// Batch 6A, UC013 - apps.audit.views::AuditLogViewSet. Read-only. The
// 504 case (QueryTimeoutError -> {"detail": TIMEOUT_MESSAGE}) is NOT
// caught here - it surfaces as a normal AxiosError the page's own catch
// block reads via parseApiErrorMessage, same as every other endpoint,
// so the server's exact verbatim copy (not a generic error) reaches
// the screen.

function toQueryParams(filters: AuditLogFilters): Record<string, string> {
  const params: Record<string, string> = {};
  if (filters.actor) params.actor = filters.actor;
  if (filters.actor_email) params.actor_email = filters.actor_email.trim();
  if (filters.action) params.action = filters.action;
  if (filters.resource_type) params.resource_type = filters.resource_type;
  if (filters.timestamp_from) params.timestamp_from = filters.timestamp_from;
  if (filters.timestamp_to) params.timestamp_to = filters.timestamp_to;
  return params;
}

export async function fetchAuditLogs(
  filters: AuditLogFilters,
  page: number = 1,
): Promise<AuditLogListResponse> {
  const { data } = await apiClient.get<AuditLogListResponse>("/audit/logs/", {
    params: { ...toQueryParams(filters), page },
  });
  return data;
}
