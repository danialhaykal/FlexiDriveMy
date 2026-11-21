import { apiClient } from "./client";
import type { Brand, CatalogFilterState, PaginatedResponse, Vehicle } from "../types/catalog";

function toQueryParams(filters: CatalogFilterState): Record<string, string> {
  const params: Record<string, string> = {};
  if (filters.brand) params.brand = filters.brand;
  if (filters.bodySegment) params.body_segment = filters.bodySegment;
  if (filters.minPrice) params.min_price = filters.minPrice;
  if (filters.maxPrice) params.max_price = filters.maxPrice;
  if (filters.search) params.search = filters.search;
  return params;
}

export async function fetchCatalog(
  filters: CatalogFilterState,
  page: number = 1,
): Promise<PaginatedResponse<Vehicle>> {
  const { data } = await apiClient.get<PaginatedResponse<Vehicle>>("/vehicles/catalog/", {
    params: { ...toQueryParams(filters), page },
  });
  return data;
}

// QA audit M23: ArenaPage's vehicle picker needs the FULL catalog (it's
// a selection UI, not a paged browsing list), but the backend's
// PageNumberPagination has no page_size override configured - changing
// that is a backend change out of proportion to "let one picker see
// everything". Looping through `next` client-side instead - a
// documented, deliberate shortcut, acceptable because this platform's
// catalog is a small, curated, admin-managed set (the project spec locks it to
// five premium brands), never a large enough list for this loop to be a
// real performance concern.
export async function fetchEntireCatalog(filters: CatalogFilterState): Promise<Vehicle[]> {
  const all: Vehicle[] = [];
  let page = 1;
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const data = await fetchCatalog(filters, page);
    all.push(...data.results);
    if (!data.next) break;
    page += 1;
  }
  return all;
}

export async function fetchCatalogBrands(): Promise<Brand[]> {
  const { data } = await apiClient.get<Brand[]>("/vehicles/catalog/brands/");
  return data;
}

export async function fetchVehicleDetail(id: number | string): Promise<Vehicle> {
  const { data } = await apiClient.get<Vehicle>(`/vehicles/catalog/${id}/`);
  return data;
}
