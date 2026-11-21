import { useEffect, useState } from "react";
import { fetchEntireCatalog } from "../api/catalog";
import { EMPTY_CATALOG_FILTERS } from "../types/catalog";
import type { Vehicle } from "../types/catalog";

// The catalog's cars by id - for a saved comparison's photo only (redesign
// UI-4). Uses the same catalog list the Arena already fetches. Only fetched
// when `enabled` (there is something to show a photo for). A car that is not
// in the list (archived) or a list that fails to load simply means no photo:
// the placeholder is shown, and the saved figures never depend on this.
export function useCatalogVehiclesById(enabled: boolean): Record<number, Vehicle> {
  const [vehiclesById, setVehiclesById] = useState<Record<number, Vehicle>>({});

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    // Started inside a promise so that any failure, even a synchronous one, ends in .catch.
    Promise.resolve()
      .then(() => fetchEntireCatalog(EMPTY_CATALOG_FILTERS))
      .then((vehicles) => {
        if (!cancelled) setVehiclesById(Object.fromEntries(vehicles.map((vehicle) => [vehicle.id, vehicle])));
      })
      .catch(() => {
        // A photo is decoration: keep the placeholders.
      });
    return () => {
      cancelled = true;
    };
  }, [enabled]);

  return vehiclesById;
}
