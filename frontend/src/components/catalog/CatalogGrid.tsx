import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { fetchCatalog, fetchCatalogBrands } from "../../api/catalog";
import { useDebouncedValue } from "../../hooks/useDebouncedValue";
import { EMPTY_CATALOG_FILTERS } from "../../types/catalog";
import type { Brand, CatalogFilterState, Vehicle } from "../../types/catalog";
import { Button } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";
import { PageHeader } from "../ui/PageHeader";
import { CatalogFilters } from "./CatalogFilters";
import { VehicleCard } from "./VehicleCard";
import { PhotoCreditLine } from "./PhotoCreditLine";

// The result count the API returned, as a subtitle ("9 cars" / "1 car").
function countLabel(count: number | null): string | undefined {
  if (count === null) return undefined;
  return count === 1 ? "1 car" : `${count} cars`;
}

// A card-shaped placeholder while the catalog loads.
function CardSkeleton() {
  return (
    <div className="overflow-hidden rounded-card border border-border bg-surface shadow-card" aria-hidden="true">
      <div className="aspect-[16/10] w-full animate-pulse bg-surface-subtle" />
      <div className="flex flex-col gap-2 p-4">
        <div className="h-3 w-24 animate-pulse rounded bg-surface-subtle" />
        <div className="h-5 w-3/4 animate-pulse rounded bg-surface-subtle" />
        <div className="h-5 w-1/3 animate-pulse rounded bg-surface-subtle" />
      </div>
    </div>
  );
}

export function CatalogGrid() {
  const [filters, setFilters] = useState<CatalogFilterState>(EMPTY_CATALOG_FILTERS);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [count, setCount] = useState<number | null>(null);
  const [hasNextPage, setHasNextPage] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // QA audit M23: there was previously no way to reach vehicle 26+ at
  // all - fetchCatalog's own `count`/`next`/`previous` were read but
  // nothing rendered a control to move between pages.
  const [page, setPage] = useState(1);
  // "Try again" after a failed load re-runs the same request.
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    fetchCatalogBrands()
      .then(setBrands)
      .catch(() => setBrands([]));
  }, []);

  // QA audit M7: brand/bodySegment are select-dropdowns (one change per
  // selection, already infrequent) - only the free-typed minPrice/
  // maxPrice/search fields are debounced, so CatalogFilters itself still
  // renders every keystroke immediately (instant visual feedback), and
  // only the FETCH this effect triggers waits for the user to pause.
  const debouncedMinPrice = useDebouncedValue(filters.minPrice);
  const debouncedMaxPrice = useDebouncedValue(filters.maxPrice);
  const debouncedSearch = useDebouncedValue(filters.search);

  // QA audit L4: computed off the RAW (immediate, non-debounced) values
  // for instant feedback - min > max is never going to resolve into a
  // valid combination no matter how long the user waits, so there's no
  // reason to debounce this specific message the way the fetch itself is.
  const minPriceNumber = Number(filters.minPrice);
  const maxPriceNumber = Number(filters.maxPrice);
  const priceRangeError =
    filters.minPrice !== "" &&
    filters.maxPrice !== "" &&
    !Number.isNaN(minPriceNumber) &&
    !Number.isNaN(maxPriceNumber) &&
    minPriceNumber > maxPriceNumber
      ? "Min price can't exceed max price."
      : null;

  useEffect(() => {
    if (priceRangeError) {
      // Invalid combination: don't call the API at all - this message is
      // never going to become "no vehicles match", it's a genuinely
      // different situation the generic empty-state text used to hide.
      setVehicles([]);
      setCount(null);
      setError(null);
      setIsLoading(false);
      return;
    }
    let cancelled = false;
    setIsLoading(true);
    fetchCatalog(
      {
        brand: filters.brand,
        bodySegment: filters.bodySegment,
        minPrice: debouncedMinPrice,
        maxPrice: debouncedMaxPrice,
        search: debouncedSearch,
      },
      page,
    )
      .then((data) => {
        if (cancelled) return;
        setVehicles(data.results);
        setCount(data.count);
        setHasNextPage(data.next !== null);
        setError(null);
      })
      .catch(() => {
        if (!cancelled) setError("Could not load the vehicle catalog. Please try again.");
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // QA audit M7: dependencies are the individual PRIMITIVE values, not
    // a freshly-constructed filters object - an object literal gets a
    // new reference on every render regardless of whether its contents
    // actually changed, which would re-trigger this effect (and
    // therefore the fetch) on every keystroke exactly as before, just one
    // level removed from the actual bug.
  }, [
    filters.brand,
    filters.bodySegment,
    debouncedMinPrice,
    debouncedMaxPrice,
    debouncedSearch,
    page,
    priceRangeError,
    reloadKey,
  ]);

  // QA audit M23: any actual filter change makes the current page
  // meaningless (it might not even exist in the new result set) - reset
  // to page 1 in the SAME handler that updates filters (not a separate
  // reactive effect keyed on the filter values), so the very first
  // fetch after a filter change already uses page=1 instead of briefly
  // re-fetching the old page number against the new filters first.
  const handleFiltersChange = (next: CatalogFilterState) => {
    setFilters(next);
    setPage(1);
  };

  const resetFilters = () => {
    setFilters(EMPTY_CATALOG_FILTERS);
    setPage(1);
  };
  const isEmptyResult = !isLoading && !error && (priceRangeError !== null || count === 0);

  return (
    <div>
      <PageHeader title="Browse cars" subtitle={countLabel(count)} className="mb-6" />
      <CatalogFilters filters={filters} brands={brands} onChange={handleFiltersChange} onReset={resetFilters} />

      {isLoading && (
        <div className="mt-6">
          <p className="sr-only" role="status">
            Loading vehicles…
          </p>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <CardSkeleton key={i} />
            ))}
          </div>
        </div>
      )}

      {error && (
        <div role="alert" className="mt-6 flex flex-wrap items-center gap-3 rounded-card border border-danger-200 bg-danger-50 p-4">
          <p className="text-small text-danger-700">{error}</p>
          <Button variant="secondary" onClick={() => setReloadKey((key) => key + 1)}>
            Try again
          </Button>
        </div>
      )}

      {/* The one Reset All Filters button is in the toolbar above (shown with
          "N filters on"), so the empty state only says what happened. */}
      {isEmptyResult && (
        <EmptyState
          className="mt-6"
          title="No cars to show"
          description={priceRangeError ?? "No vehicles match your selected criteria. Please broaden your filter parameters."}
        />
      )}

      {!isLoading && !error && count !== null && count > 0 && (
        <>
          <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {vehicles.map((vehicle) => (
              <VehicleCard key={vehicle.id} vehicle={vehicle} />
            ))}
          </div>
          {/* QA audit M23: page-number controls (not infinite scroll) -
              the catalog is a small, curated, admin-managed list
              (the project spec locks it to five premium brands), so the total
              page count is always low; "Previous"/"Next" plus the
              current page number is simpler to implement and test than
              an infinite-scroll observer, with no real downside at this
              list size. */}
          <div className="mt-6 flex items-center justify-between">
            <Button variant="secondary" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page === 1}>
              <ChevronLeft className="h-4 w-4" aria-hidden="true" />
              Previous
            </Button>
            <span className="text-small text-ink-muted">Page {page}</span>
            <Button variant="secondary" onClick={() => setPage((p) => p + 1)} disabled={!hasNextPage}>
              Next
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
          {/* FX-2 (item 8) */}
          <div className="mt-4">
            <PhotoCreditLine thumbnailUrls={vehicles.map((vehicle) => vehicle.thumbnail_url)} />
          </div>
        </>
      )}
    </div>
  );
}
