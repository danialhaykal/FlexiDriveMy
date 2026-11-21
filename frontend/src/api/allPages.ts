import { apiClient } from "./client";

// Run 3 fix batch 4 (F-17): every admin list loads ALL of its rows. The admin
// API pages at 25 (DRF PageNumberPagination); the admin screens used to keep
// page 1 only, so row 26 onward (a new car, the 26th residual override) could
// not be seen, edited or archived. This helper follows `next` until the last
// page, the same way listScenarios / fetchEntireCatalog already did.
//
// A safety cap stops a runaway loop. If it is ever reached the list carries the
// server's real `count` as `total`, and the screen says "Showing N of M"
// (ListCapNotice) rather than silently dropping rows.

export const MAX_LIST_PAGES = 100; // 2,500 rows at 25 a page

interface Page<T> {
  count: number;
  next: string | null;
  results: T[];
}

// An ordinary array (every caller keeps using it as one) that also carries the
// server's row count when the cap cut it short.
export type FullList<T> = T[] & { total?: number };

export async function fetchAllPages<T>(
  path: string,
  params?: Record<string, unknown>,
  maxPages: number = MAX_LIST_PAGES,
): Promise<FullList<T>> {
  const rows: FullList<T> = [];
  let url: string | null = path;
  let first = true;
  let count = 0;
  let pages = 0;
  while (url && pages < maxPages) {
    // Only the first request carries the params: `next` already has them.
    const response: { data: Page<T> } = await apiClient.get<Page<T>>(url, first ? { params } : undefined);
    const { data } = response;
    rows.push(...data.results);
    count = data.count;
    url = data.next;
    first = false;
    pages += 1;
  }
  if (url && count > rows.length) rows.total = count;
  return rows;
}

// The server's row count when the list was cut short, else the length.
export function listTotal<T>(list: FullList<T>): number {
  return list.total ?? list.length;
}
