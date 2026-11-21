import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "./client";
import { listScenarios } from "./scenarios";
import type { Scenario } from "../types/scenarios";

// C1: the list endpoint uses DRF's default PageNumberPagination
// ({count, next, previous, results}), not a bare array - a prior version
// of listScenarios treated the response as Scenario[] directly, which
// crashed every page that called .map()/.length on it (TypeError:
// scenarios.map is not a function) the moment a real paginated response
// came back. These tests exercise listScenarios's own implementation
// against that real shape, rather than mocking listScenarios itself away
// (which is what ScenariosPage.test.tsx/DashboardPage.test.tsx do, and
// is why they never caught this bug).

vi.mock("./client", () => ({
  apiClient: { get: vi.fn() },
}));

const mockedGet = vi.mocked(apiClient.get);

function makeScenario(id: number): Scenario {
  return {
    id,
    title: `Scenario ${id}`,
    vehicle: 1,
    vehicle_label: "Test Vehicle",
    payload: {
      tenureMonths: 36,
      mileageBand: "standard",
      downpayment: "40000.00",
      comparison: {} as never,
      tco: null,
      scoring: null,
    },
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

describe("listScenarios", () => {
  beforeEach(() => {
    mockedGet.mockReset();
  });

  it("unwraps a single-page paginated response into a plain array", async () => {
    mockedGet.mockResolvedValueOnce({
      data: { count: 2, next: null, previous: null, results: [makeScenario(1), makeScenario(2)] },
    });

    const result = await listScenarios();

    expect(result).toEqual([makeScenario(1), makeScenario(2)]);
    expect(mockedGet).toHaveBeenCalledTimes(1);
    expect(mockedGet).toHaveBeenCalledWith("/scenarios/");
  });

  it("follows `next` until every page is loaded, so a user with 26+ scenarios sees all of them", async () => {
    mockedGet
      .mockResolvedValueOnce({
        data: {
          count: 3,
          next: "http://localhost:8000/api/scenarios/?page=2",
          previous: null,
          results: [makeScenario(1), makeScenario(2)],
        },
      })
      .mockResolvedValueOnce({
        data: { count: 3, next: null, previous: "http://localhost:8000/api/scenarios/?page=1", results: [makeScenario(3)] },
      });

    const result = await listScenarios();

    expect(result.map((scenario) => scenario.id)).toEqual([1, 2, 3]);
    expect(mockedGet).toHaveBeenCalledTimes(2);
    expect(mockedGet).toHaveBeenNthCalledWith(1, "/scenarios/");
    expect(mockedGet).toHaveBeenNthCalledWith(2, "http://localhost:8000/api/scenarios/?page=2");
  });

  it("returns an empty array when there are no saved scenarios", async () => {
    mockedGet.mockResolvedValueOnce({
      data: { count: 0, next: null, previous: null, results: [] },
    });

    const result = await listScenarios();

    expect(result).toEqual([]);
  });
});
