import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { resetMileageBandOptionsCache, useMileageBandOptions } from "./useMileageBandOptions";
import { fetchMileageBands } from "../api/mileageBands";
import { MILEAGE_BAND_OPTIONS } from "../types/comparisons";
import type { MileageBandOption } from "../types/comparisons";
import { API_MILEAGE_BANDS } from "../test/mileageBandsFixture";

vi.mock("../api/mileageBands", () => ({ fetchMileageBands: vi.fn() }));
const mockedFetch = vi.mocked(fetchMileageBands);

// What the API sends (the one test fixture): every band's label and range come from
// the backend's policy data, so they are data, not figures written into the page.
// The very high band is edited here to show a changed policy value comes through.
const FROM_API: MileageBandOption[] = API_MILEAGE_BANDS.map((band) =>
  band.value === "very_high" ? { ...band, label: `${band.label} (edited policy)` } : band,
);

describe("useMileageBandOptions", () => {
  beforeEach(() => {
    resetMileageBandOptionsCache();
    mockedFetch.mockReset();
  });

  it("starts on the built-in names and switches to the API's labels, with their ranges", async () => {
    mockedFetch.mockResolvedValue(FROM_API);

    const { result } = renderHook(() => useMileageBandOptions());

    expect(result.current).toBe(MILEAGE_BAND_OPTIONS);
    await waitFor(() => expect(result.current).toEqual(FROM_API));
    expect(result.current[3].label).toBe(FROM_API[3].label);
    expect(MILEAGE_BAND_OPTIONS.map((o) => o.label)).toEqual(["Low", "Standard", "High", "Very high"]);
  });

  it("keeps the built-in list, quietly, when the API can't be reached", async () => {
    mockedFetch.mockRejectedValue(new Error("network down"));

    const { result } = renderHook(() => useMileageBandOptions());
    await waitFor(() => expect(mockedFetch).toHaveBeenCalled());

    expect(result.current).toBe(MILEAGE_BAND_OPTIONS);
    expect(result.current.map((o) => o.value)).toEqual(["low", "standard", "high", "very_high"]);
  });

  it("fetches once and shares the answer with every screen that uses it", async () => {
    mockedFetch.mockResolvedValue(FROM_API);

    const first = renderHook(() => useMileageBandOptions());
    await waitFor(() => expect(first.result.current).toEqual(FROM_API));
    const second = renderHook(() => useMileageBandOptions());

    expect(second.result.current).toEqual(FROM_API); // immediately, from the shared copy
    expect(mockedFetch).toHaveBeenCalledTimes(1);
  });
});
