import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "./client";
import { fetchAllPages, listTotal } from "./allPages";
import { fetchAdminBrands, fetchAdminVehicles } from "./adminFleet";
import {
  fetchContractPenaltyRules,
  fetchInterestRates,
  fetchResidualValueMatrix,
  fetchSubscriptionPlans,
} from "./policy";
import { fetchTrainingRuns } from "./ml";

// Run 3 fix batch 4 (F-17): every admin list loads all of its pages. Before the
// fix each of these returned page 1 only (25 rows), so e.g. Residual Overrides
// showed 25 of 93 rows. Each list is checked against a 60-row mock served as
// three pages (25 + 25 + 10), exactly as DRF's PageNumberPagination sends it.

vi.mock("./client", () => ({
  apiClient: { get: vi.fn() },
}));

const mockedGet = vi.mocked(apiClient.get);

function row(id: number) {
  return { id, name: `Row ${id}`, is_active: id % 7 !== 0 };
}

const ROWS = Array.from({ length: 60 }, (_, i) => row(i + 1));

function serveThreePages(path: string, query: string) {
  const base = `http://localhost:8000/api${path}`;
  const sep = query ? "&" : "?";
  const pages = [ROWS.slice(0, 25), ROWS.slice(25, 50), ROWS.slice(50)];
  pages.forEach((results, i) => {
    mockedGet.mockResolvedValueOnce({
      data: {
        count: 60,
        next: i < 2 ? `${base}${query}${sep}page=${i + 2}` : null,
        previous: i > 0 ? `${base}${query}${sep}page=${i}` : null,
        results,
      },
    });
  });
  return [`${base}${query}${sep}page=2`, `${base}${query}${sep}page=3`];
}

const LISTS: { name: string; fn: () => Promise<unknown[]>; path: string; params?: Record<string, unknown> }[] = [
  { name: "Fleet vehicles", fn: fetchAdminVehicles, path: "/vehicles/models/", params: { include_archived: true } },
  { name: "Fleet brands", fn: fetchAdminBrands, path: "/vehicles/brands/", params: { include_archived: true } },
  { name: "interest rates", fn: fetchInterestRates, path: "/policy/interest-rates/", params: { include_archived: true } },
  { name: "residual overrides", fn: fetchResidualValueMatrix, path: "/policy/residual-value-matrix/", params: { include_archived: true } },
  { name: "provider quotes", fn: fetchSubscriptionPlans, path: "/policy/subscription-plans/", params: { include_archived: true } },
  { name: "contract rules", fn: fetchContractPenaltyRules, path: "/policy/contract-penalty-rules/", params: { include_archived: true } },
  { name: "ML training runs", fn: fetchTrainingRuns, path: "/ml/training-runs/", params: undefined },
];

describe.each(LISTS)("$name", ({ fn, path, params }) => {
  beforeEach(() => {
    mockedGet.mockReset();
  });

  it("loads all 60 rows over three pages, in the server's order and unchanged", async () => {
    const query = params ? "?include_archived=true" : "";
    const [page2, page3] = serveThreePages(path, query);

    const result = await fn();

    expect(result).toHaveLength(60);
    expect(result).toEqual(ROWS); // every row exactly as the server sent it
    expect(listTotal(result)).toBe(60);
    expect(mockedGet).toHaveBeenCalledTimes(3);
    // The first request is the same one the screen made before this fix.
    expect(mockedGet).toHaveBeenNthCalledWith(1, path, { params });
    // The next pages are read from `next` (which already carries the filters).
    expect(mockedGet).toHaveBeenNthCalledWith(2, page2, undefined);
    expect(mockedGet).toHaveBeenNthCalledWith(3, page3, undefined);
  });

  it("still works for a list that fits on one page", async () => {
    mockedGet.mockResolvedValueOnce({ data: { count: 2, next: null, previous: null, results: [row(1), row(2)] } });

    const result = await fn();

    expect(result).toEqual([row(1), row(2)]);
    expect(mockedGet).toHaveBeenCalledTimes(1);
  });
});

describe("fetchAllPages safety cap", () => {
  beforeEach(() => {
    mockedGet.mockReset();
  });

  it("stops at the cap and keeps the server's total so the screen can say 'Showing N of M'", async () => {
    serveThreePages("/policy/residual-value-matrix/", "?include_archived=true");

    const result = await fetchAllPages("/policy/residual-value-matrix/", { include_archived: true }, 2);

    expect(result).toHaveLength(50);
    expect(result.total).toBe(60);
    expect(listTotal(result)).toBe(60);
    expect(mockedGet).toHaveBeenCalledTimes(2);
  });

  it("marks nothing when every page was read", async () => {
    serveThreePages("/vehicles/models/", "?include_archived=true");

    const result = await fetchAllPages("/vehicles/models/", { include_archived: true });

    expect(result.total).toBeUndefined();
    expect(listTotal(result)).toBe(60);
  });
});
