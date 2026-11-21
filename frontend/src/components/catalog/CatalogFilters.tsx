import { RotateCcw, Search } from "lucide-react";
import { BODY_SEGMENT_OPTIONS } from "../../types/catalog";
import type { Brand, CatalogFilterState } from "../../types/catalog";
import { cn } from "../ui/cn";

interface CatalogFiltersProps {
  filters: CatalogFilterState;
  brands: Brand[];
  onChange: (filters: CatalogFilterState) => void;
  onReset: () => void;
}

// How many filters are set (search, brand, body segment, min price, max price).
export function activeFilterCount(filters: CatalogFilterState): number {
  return [filters.search, filters.brand, filters.bodySegment, filters.minPrice, filters.maxPrice].filter(
    (value) => value !== "",
  ).length;
}

const FIELD =
  "w-full rounded-control border border-border bg-surface px-3 py-2 text-small text-ink focus:border-primary-500 focus:outline-none focus:ring-2 focus:ring-primary-500/30";
const LABEL = "block text-caption font-semibold text-ink-muted";

// One compact toolbar: search first, brand, the body segment as toggle chips
// (one at a time, "All" first), and the price range side by side. On a phone
// the toolbar stacks and the chip row scrolls sideways inside itself.
export function CatalogFilters({ filters, brands, onChange, onReset }: CatalogFiltersProps) {
  const update = (patch: Partial<CatalogFilterState>) => onChange({ ...filters, ...patch });
  const count = activeFilterCount(filters);
  const chips = [{ value: "", label: "All" }, ...BODY_SEGMENT_OPTIONS];

  return (
    <form
      aria-label="Catalog filters"
      onSubmit={(event) => event.preventDefault()}
      className="rounded-card border border-border bg-surface p-4 shadow-card"
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,1.4fr)]">
        <div>
          <label htmlFor="filter-search" className={LABEL}>
            Search
          </label>
          <div className="relative mt-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" aria-hidden="true" />
            <input
              id="filter-search"
              type="search"
              placeholder="Brand, model, trim…"
              value={filters.search}
              onChange={(event) => update({ search: event.target.value })}
              className={cn(FIELD, "pl-9")}
            />
          </div>
        </div>

        <div>
          <label htmlFor="filter-brand" className={LABEL}>
            Brand
          </label>
          <select
            id="filter-brand"
            value={filters.brand}
            onChange={(event) => update({ brand: event.target.value })}
            className={cn(FIELD, "mt-1")}
          >
            <option value="">All brands</option>
            {brands.map((brand) => (
              <option key={brand.id} value={brand.id}>
                {brand.name}
              </option>
            ))}
          </select>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:col-span-2 lg:col-span-1">
          <div>
            <label htmlFor="filter-min-price" className={LABEL}>
              Min price (RM)
            </label>
            <input
              id="filter-min-price"
              type="number"
              min="0"
              value={filters.minPrice}
              onChange={(event) => update({ minPrice: event.target.value })}
              className={cn(FIELD, "mt-1")}
            />
          </div>
          <div>
            <label htmlFor="filter-max-price" className={LABEL}>
              Max price (RM)
            </label>
            <input
              id="filter-max-price"
              type="number"
              min="0"
              value={filters.maxPrice}
              onChange={(event) => update({ maxPrice: event.target.value })}
              className={cn(FIELD, "mt-1")}
            />
          </div>
        </div>
      </div>

      <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div role="group" aria-label="Body segment" className="scrollbar-none -mx-1 flex min-w-0 gap-1.5 overflow-x-auto px-1 py-0.5">
          {chips.map((chip) => {
            const isOn = filters.bodySegment === chip.value;
            return (
              <button
                key={chip.value || "all"}
                type="button"
                aria-pressed={isOn}
                onClick={() => update({ bodySegment: chip.value })}
                className={cn(
                  "shrink-0 whitespace-nowrap rounded-full border px-3 py-1 text-small transition-colors",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500",
                  isOn
                    ? "border-primary-600 bg-primary-50 font-semibold text-primary-700"
                    : "border-border bg-surface font-medium text-ink-muted hover:text-ink",
                )}
              >
                {chip.label}
              </button>
            );
          })}
        </div>
        <div className="flex shrink-0 items-center gap-3">
          {count > 0 && (
            <span className="text-caption font-semibold text-ink-muted" aria-live="polite">
              {count === 1 ? "1 filter on" : `${count} filters on`}
            </span>
          )}
          <button
            type="button"
            onClick={onReset}
            disabled={count === 0}
            className="inline-flex items-center gap-1.5 rounded-control border border-border bg-surface px-3 py-1.5 text-small font-semibold text-ink hover:bg-surface-subtle focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <RotateCcw className="h-4 w-4" aria-hidden="true" />
            Reset All Filters
          </button>
        </div>
      </div>
    </form>
  );
}
