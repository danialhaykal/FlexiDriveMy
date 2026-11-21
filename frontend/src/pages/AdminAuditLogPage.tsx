import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import axios from "axios";
import { fetchAuditLogs } from "../api/audit";
import { parseApiErrorMessage } from "../lib/apiErrors";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { AUDIT_ACTION_OPTIONS } from "../types/audit";
import type { AuditLog, AuditLogFilters } from "../types/audit";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { Drawer } from "../components/ui/Drawer";
import { EmptyState } from "../components/ui/EmptyState";
import { InfoExpander } from "../components/ui/InfoExpander";
import { Input } from "../components/ui/Input";
import { LoadingSkeleton } from "../components/ui/LoadingSkeleton";
import { PageHeader } from "../components/ui/PageHeader";
import { Select } from "../components/ui/Select";
import { Table } from "../components/ui/Table";
import { cn } from "../components/ui/cn";
import { auditResourceName, changedAuditKeys, formatAuditValue, readableAuditKey } from "../lib/auditDisplay";
import { formatAdminDateTime } from "../lib/formatAdminDate";

// Batch 6A, UC013 - System Log & Audit Trail Management. Read-only (the
// backend AuditLogViewSet is itself read-only - rows are only ever
// written internally via AuditedModelViewSet). The 504 timeout case
// (apps.audit.views::TIMEOUT_MESSAGE) is shown through the SAME
// parseApiErrorMessage path every other page uses, verbatim - not a
// generic "something went wrong", since UC013's alt flow specifically
// wants the server's own narrow-the-date-range guidance to reach the
// user.
//
// Redesign UI-6b: one compact filter bar (same fields, same parameters), each
// action as a coloured badge with its label, and a row's details in a side
// panel: before / after as a readable list, the raw data folded under it.

const EMPTY_FILTERS: AuditLogFilters = {
  actor_email: "",
  action: "",
  resource_type: "",
  timestamp_from: "",
  timestamp_to: "",
};

const GENERIC_ERROR = "Could not load audit log entries. Please try again.";
export const NOTHING_BEFORE = "Nothing before (new record)";
export const NOTHING_RECORDED = "Nothing recorded";

// The action's badge: a colour by kind, and always its label (never the raw key).
const ACTION_BADGE: Record<AuditLog["action"], { tone: "positive" | "neutral" | "warning" | "danger"; label: string }> = {
  create: { tone: "positive", label: "Create" },
  update: { tone: "neutral", label: "Update" },
  archive: { tone: "warning", label: "Archive" },
  bulk_import: { tone: "neutral", label: "Bulk Import" },
  runtime_error: { tone: "danger", label: "Error" },
};

function ActionBadge({ action }: { action: AuditLog["action"] }) {
  const badge = ACTION_BADGE[action] ?? { tone: "neutral" as const, label: action };
  return <Badge tone={badge.tone}>{badge.label}</Badge>;
}

// One side of a change as a key-value list; an empty side says why in words.
// FX-3 (X13): values formatted like the policy page (lib/auditDisplay.ts), and
// a field whose value changed is tinted and marked "Changed".
function ChangeSide({
  title,
  data,
  emptyText,
  changed,
}: {
  title: string;
  data: Record<string, unknown> | null;
  emptyText: string;
  changed: Set<string>;
}) {
  return (
    <section>
      <h3 className="text-small font-semibold text-ink">{title}</h3>
      {data === null || data === undefined ? (
        <p className="mt-1 text-small text-ink-muted">{emptyText}</p>
      ) : (
        <dl className="mt-2 divide-y divide-border rounded-control border border-border">
          {Object.entries(data).map(([key, value]) => {
            const isChanged = changed.has(key);
            return (
              <div
                key={key}
                data-changed={isChanged ? "true" : undefined}
                className={cn(
                  "grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-3 px-3 py-2 text-small",
                  isChanged && "bg-warning-50",
                )}
              >
                <dt className={isChanged ? "font-semibold text-ink" : "text-ink-muted"}>
                  <span>{readableAuditKey(key)}</span>
                  {isChanged && <span className="ml-1.5 text-caption font-normal text-warning-700">Changed</span>}
                </dt>
                <dd className={cn("break-words text-ink", isChanged && "font-semibold")}>{formatAuditValue(key, value)}</dd>
              </div>
            );
          })}
        </dl>
      )}
    </section>
  );
}

export function AdminAuditLogPage() {
  useDocumentTitle("Audit Log");

  const [filters, setFilters] = useState<AuditLogFilters>(EMPTY_FILTERS);
  const [logs, setLogs] = useState<AuditLog[]>([]);
  const [count, setCount] = useState(0);
  const [hasNextPage, setHasNextPage] = useState(false);
  const [hasPreviousPage, setHasPreviousPage] = useState(false);
  const [page, setPage] = useState(1);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [openLog, setOpenLog] = useState<AuditLog | null>(null);

  function load(activeFilters: AuditLogFilters, activePage: number) {
    setIsLoading(true);
    setError(null);
    fetchAuditLogs(activeFilters, activePage)
      .then((data) => {
        setLogs(data.results);
        setCount(data.count);
        setHasNextPage(data.next !== null);
        setHasPreviousPage(data.previous !== null);
      })
      .catch((err: unknown) => {
        setError(
          (axios.isAxiosError(err) && parseApiErrorMessage(err.response?.data)) || GENERIC_ERROR,
        );
        setLogs([]);
        setHasNextPage(false);
        setHasPreviousPage(false);
      })
      .finally(() => setIsLoading(false));
  }

  useEffect(() => {
    load(EMPTY_FILTERS, 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleFilterSubmit(event: FormEvent) {
    event.preventDefault();
    setPage(1);
    setOpenLog(null);
    load(filters, 1);
  }

  function handleResetFilters() {
    setFilters(EMPTY_FILTERS);
    setPage(1);
    setOpenLog(null);
    load(EMPTY_FILTERS, 1);
  }

  function goToPage(nextPage: number) {
    setPage(nextPage);
    setOpenLog(null);
    load(filters, nextPage);
  }

  const changedKeys = changedAuditKeys(openLog?.before_data, openLog?.after_data);

  // A hint for the free-text resource type: the types in the rows on screen.
  const seenResourceTypes = Array.from(new Set(logs.map((log) => log.resource_type).filter(Boolean))).sort();

  return (
    <div className="mx-auto max-w-6xl px-4 pb-16 pt-8 sm:pt-10">
      <PageHeader title="Audit log" subtitle="Every admin change and system error, append-only." />

      <Card className="mt-6" padding="none">
        <form
          className="grid grid-cols-1 items-end gap-3 p-4 sm:grid-cols-2 sm:p-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1.2fr)_minmax(0,0.9fr)_minmax(0,0.9fr)]"
          onSubmit={handleFilterSubmit}
        >
          <Input
            label="User email"
            placeholder="Filter by user email"
            value={filters.actor_email ?? ""}
            onChange={(e) => setFilters((prev) => ({ ...prev, actor_email: e.target.value }))}
          />
          <Select
            label="Action"
            value={filters.action}
            onChange={(e) =>
              setFilters((prev) => ({
                ...prev,
                action: e.target.value as AuditLogFilters["action"],
              }))
            }
            options={[{ value: "", label: "All actions" }, ...AUDIT_ACTION_OPTIONS]}
          />
          <Input
            label="Resource type"
            placeholder="e.g. InterestRate or policy.InterestRate (any case)"
            list="audit-resource-types"
            value={filters.resource_type}
            onChange={(e) => setFilters((prev) => ({ ...prev, resource_type: e.target.value }))}
          />
          <Input
            label="From"
            type="date"
            value={filters.timestamp_from}
            onChange={(e) => setFilters((prev) => ({ ...prev, timestamp_from: e.target.value }))}
          />
          <Input
            label="To"
            type="date"
            value={filters.timestamp_to}
            onChange={(e) => setFilters((prev) => ({ ...prev, timestamp_to: e.target.value }))}
          />
          <datalist id="audit-resource-types">
            {seenResourceTypes.map((type) => (
              <option key={type} value={type} />
            ))}
          </datalist>
          <div className="flex gap-2 sm:col-span-2 lg:col-span-5">
            <Button type="submit">Apply Filters</Button>
            <Button type="button" variant="ghost" onClick={handleResetFilters}>
              Reset
            </Button>
          </div>
        </form>
      </Card>

      <div className="mt-6">
        {isLoading && <LoadingSkeleton className="h-64 w-full" />}

        {!isLoading && error && (
          <div role="alert">
            <EmptyState
              title="Log query failed"
              description={error}
              action={<Button onClick={() => load(filters, page)}>Try again</Button>}
            />
          </div>
        )}

        {!isLoading && !error && logs.length === 0 && (
          <EmptyState title="No matching audit log entries" description="Try a wider filter range." />
        )}

        {!isLoading && !error && logs.length > 0 && (
          <Card padding="none">
            <Table>
              <Table.Head>
                <Table.Row>
                  <Table.HeaderCell>Time</Table.HeaderCell>
                  <Table.HeaderCell>Actor</Table.HeaderCell>
                  <Table.HeaderCell>Action</Table.HeaderCell>
                  <Table.HeaderCell>Resource</Table.HeaderCell>
                  <Table.HeaderCell>IP address</Table.HeaderCell>
                </Table.Row>
              </Table.Head>
              <Table.Body>
                {logs.map((log) => (
                  <Table.Row key={log.id}>
                    <Table.Cell>
                      {/* Opens the row's details in the side panel. */}
                      <button
                        type="button"
                        aria-haspopup="dialog"
                        className="whitespace-nowrap rounded-control text-left font-medium text-primary-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
                        onClick={() => setOpenLog(log)}
                      >
                        {formatAdminDateTime(log.timestamp)}
                      </button>
                    </Table.Cell>
                    <Table.Cell className="break-all">{log.actor_email || `#${log.actor_id ?? "unknown"}`}</Table.Cell>
                    <Table.Cell>
                      <ActionBadge action={log.action} />
                    </Table.Cell>
                    <Table.Cell>{auditResourceName(log.resource_type, log.resource_id)}</Table.Cell>
                    <Table.Cell className="whitespace-nowrap">{log.ip_address || "-"}</Table.Cell>
                  </Table.Row>
                ))}
              </Table.Body>
            </Table>

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3">
              <span className="text-small text-ink-muted">
                Page {page} · {count.toLocaleString("en-MY")} total entries
              </span>
              <div className="flex gap-2">
                <Button variant="secondary" disabled={!hasPreviousPage} onClick={() => goToPage(page - 1)}>
                  Previous
                </Button>
                <Button variant="secondary" disabled={!hasNextPage} onClick={() => goToPage(page + 1)}>
                  Next
                </Button>
              </div>
            </div>
          </Card>
        )}
      </div>

      <Drawer
        isOpen={openLog !== null}
        title="Audit entry"
        subtitle={
          openLog && (
            <span className="flex flex-wrap items-center gap-2">
              <ActionBadge action={openLog.action} />
              {formatAdminDateTime(openLog.timestamp)} · {auditResourceName(openLog.resource_type, openLog.resource_id)}
            </span>
          )
        }
        onClose={() => setOpenLog(null)}
      >
        {openLog && (
          <div className="flex flex-col gap-5">
            <p className="text-small text-ink-muted">
              By {openLog.actor_email || `#${openLog.actor_id ?? "unknown"}`}
              {openLog.ip_address ? ` from ${openLog.ip_address}` : ""}.
            </p>
            {/* Run 3 fix batch 5 (F-30a): a create has nothing before it - say so
                in words, not a bare "null" (a runtime-error row has none either). */}
            <ChangeSide
              title="Before"
              data={openLog.before_data}
              emptyText={openLog.action === "create" ? NOTHING_BEFORE : NOTHING_RECORDED}
              changed={changedKeys}
            />
            <ChangeSide title="After" data={openLog.after_data} emptyText={NOTHING_RECORDED} changed={changedKeys} />
            <InfoExpander summary="Raw data">
              <div className="flex flex-col gap-3">
                <p className="text-caption text-ink-muted">
                  Resource: <code className="text-ink">{openLog.resource_type}</code> #{openLog.resource_id}
                </p>
                {openLog.before_data !== null && openLog.before_data !== undefined && (
                  <div>
                    <p className="text-caption font-semibold text-ink">Before</p>
                    <pre className="mt-1 overflow-x-auto whitespace-pre-wrap text-caption text-ink-muted">
                      {JSON.stringify(openLog.before_data, null, 2)}
                    </pre>
                  </div>
                )}
                {openLog.after_data !== null && openLog.after_data !== undefined && (
                  <div>
                    <p className="text-caption font-semibold text-ink">After</p>
                    <pre className="mt-1 overflow-x-auto whitespace-pre-wrap text-caption text-ink-muted">
                      {JSON.stringify(openLog.after_data, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            </InfoExpander>
          </div>
        )}
      </Drawer>
    </div>
  );
}
