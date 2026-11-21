import { useEffect, useState } from "react";
import { fetchMileageBands } from "../api/mileageBands";
import { MILEAGE_BAND_OPTIONS } from "../types/comparisons";
import type { MileageBandOption } from "../types/comparisons";

// The mileage bands to offer, from the one shared source (the API). Shows the
// built-in list until the API answers, and keeps it if the API can't be
// reached - a convenience fetch must never block a screen. Fetched once per
// page load and shared by every screen that uses it.
let cached: MileageBandOption[] | null = null;
let inFlight: Promise<MileageBandOption[]> | null = null;

// Tests only: forget what was fetched.
export function resetMileageBandOptionsCache() {
  cached = null;
  inFlight = null;
}

export function useMileageBandOptions(): MileageBandOption[] {
  const [options, setOptions] = useState<MileageBandOption[]>(cached ?? MILEAGE_BAND_OPTIONS);

  useEffect(() => {
    if (cached) {
      setOptions(cached);
      return;
    }
    let cancelled = false;
    inFlight ??= fetchMileageBands();
    inFlight
      .then((data) => {
        cached = data;
        if (!cancelled) setOptions(data);
      })
      .catch(() => {
        inFlight = null; // try again next time; keep the built-in list for now
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return options;
}
