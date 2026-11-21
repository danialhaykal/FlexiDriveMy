import { useState } from "react";
import type { ReactNode } from "react";
import { Search } from "lucide-react";
import { cn } from "../ui/cn";

// The admin list pattern (redesign UI-6a): a search box over the loaded rows'
// visible text, an Active / Archived / All filter with a count for each
// (Active by default, so old archived rows don't crowd the live data), room
// for a page's own extra filter, and the page's main action on the right.
// It only FILTERS the rows already loaded - every list still loads all of its
// rows (api/allPages.ts), so All plus a search reaches every row.
//
// Usage:
//   const list = useAdminListFilter(vehicles, (v) => v.is_active, (v) => `${v.brand_name} ${v.name} ${v.trim}`);
//   <AdminListToolbar searchLabel="Search vehicles" {...list.toolbarProps} action={<Button>Add</Button>} />
//   {list.visible.map(...)}

export type StatusFilter = "active" | "archived" | "all";

const STATUS_LABELS: Record<StatusFilter, string> = { active: "Active", archived: "Archived", all: "All" };

export interface StatusCounts {
  active: number;
  archived: number;
  all: number;
}

export function useAdminListFilter<T>(
  rows: T[],
  isActive: (row: T) => boolean,
  searchText: (row: T) => string,
  extraFilter?: (row: T) => boolean,
) {
  const [status, setStatus] = useState<StatusFilter>("active");
  const [search, setSearch] = useState("");

  // The counts are over every loaded row (before the search), so they match the server's lists.
  const activeCount = rows.filter(isActive).length;
  const counts: StatusCounts = { active: activeCount, archived: rows.length - activeCount, all: rows.length };

  const needle = search.trim().toLowerCase();
  const visible = rows.filter((row) => {
    if (status === "active" && !isActive(row)) return false;
    if (status === "archived" && isActive(row)) return false;
    if (extraFilter && !extraFilter(row)) return false;
    return needle === "" || searchText(row).toLowerCase().includes(needle);
  });

  return {
    status,
    setStatus,
    search,
    setSearch,
    visible,
    counts,
    toolbarProps: { status, onStatusChange: setStatus, search, onSearchChange: setSearch, counts },
  };
}

interface AdminListToolbarProps {
  searchLabel: string;
  search: string;
  onSearchChange: (value: string) => void;
  status: StatusFilter;
  onStatusChange: (status: StatusFilter) => void;
  counts: StatusCounts;
  // A page's own extra filter(s), e.g. a brand select.
  children?: ReactNode;
  // The page's main action for this list (e.g. "Add Interest Rate").
  action?: ReactNode;
}

export function AdminListToolbar({
  searchLabel,
  search,
  onSearchChange,
  status,
  onStatusChange,
  counts,
  children,
  action,
}: AdminListToolbarProps) {
  return (
    <div className="flex flex-wrap items-end gap-3">
      <label className="flex min-w-0 flex-1 basis-56 flex-col gap-1.5">
        <span className="text-small font-medium text-ink">{searchLabel}</span>
        <span className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" aria-hidden="true" />
          <input
            type="search"
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            className="w-full rounded-control border border-border bg-surface py-2 pl-9 pr-3 text-body text-ink focus:outline-none focus:ring-2 focus:ring-primary-500"
          />
        </span>
      </label>
      <div role="group" aria-label="Show" className="flex rounded-control border border-border bg-surface-subtle p-0.5">
        {(Object.keys(STATUS_LABELS) as StatusFilter[]).map((key) => (
          <button
            key={key}
            type="button"
            aria-pressed={status === key}
            onClick={() => onStatusChange(key)}
            className={cn(
              "rounded-[7px] px-3 py-1.5 text-small font-medium transition-colors",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500",
              status === key ? "bg-surface text-ink shadow-sm" : "text-ink-muted hover:text-ink",
            )}
          >
            {STATUS_LABELS[key]} ({counts[key].toLocaleString("en-MY")})
          </button>
        ))}
      </div>
      {children}
      {action && <div className="ml-auto flex items-end">{action}</div>}
    </div>
  );
}

// What an empty filtered list says (never the same as "nothing configured").
export function NoMatchingRows({ status, hasSearch }: { status: StatusFilter; hasSearch: boolean }) {
  const text = hasSearch
    ? "No rows match your search."
    : status === "archived"
      ? "No archived rows."
      : status === "active"
        ? "No active rows. Choose All to see archived ones."
        : "No rows.";
  return <p className="px-4 py-6 text-center text-small text-ink-muted">{text}</p>;
}
