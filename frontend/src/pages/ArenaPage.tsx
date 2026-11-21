import { useEffect, useState } from "react";
import axios from "axios";
import { Columns3 } from "lucide-react";
import { fetchEntireCatalog } from "../api/catalog";
import { fetchArena } from "../api/comparisons";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useMileageBandOptions } from "../hooks/useMileageBandOptions";
import { parseApiErrorMessage } from "../lib/apiErrors";
import { formatCurrency } from "../lib/formatCurrency";
import { DEFAULT_TENURE_MONTHS } from "../lib/defaults";
import { TENURE_MARKS, notOfferedHint } from "../lib/tenureMarks";
import { EMPTY_CATALOG_FILTERS } from "../types/catalog";
import type { Vehicle } from "../types/catalog";
import type { MileageBand } from "../types/comparisons";
import type { ArenaResult } from "../types/arena";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { InfoExpander } from "../components/ui/InfoExpander";
import { Input } from "../components/ui/Input";
import { LoadingSkeleton } from "../components/ui/LoadingSkeleton";
import { PageHeader } from "../components/ui/PageHeader";
import { RangeSlider } from "../components/ui/RangeSlider";
import { Select } from "../components/ui/Select";
import { ArenaTable } from "../components/comparisons/ArenaTable";
import { VehiclePicker } from "../components/comparisons/VehiclePicker";

// Sprint 10 - a 2-3 vehicle side-by-side "Arena" comparison. Pure
// orchestration server-side (apps.comparisons.arena.build_arena calls
// F005/F006's already-tested build_comparison()/build_tco_report() once
// per vehicle) - this page only collects the picker + shared
// tenure/mileage/downpayment inputs and renders exactly what
// GET /api/comparisons/arena/ returns, same "never recompute" rule as
// ComparisonPage.

const GENERIC_ERROR = "Could not calculate this arena comparison. Please try again.";
// Run 3 fix batch 5 (F-29): a car list that could not load is said plainly, with a retry.
export const VEHICLES_LOAD_ERROR = "Could not load the list of cars. Please try again.";
const MIN_ARENA_VEHICLES = 2;
const MAX_ARENA_VEHICLES = 3;

export function ArenaPage() {
  useDocumentTitle("Compare Cars");
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [isVehiclesLoading, setIsVehiclesLoading] = useState(true);
  const [vehiclesError, setVehiclesError] = useState<string | null>(null);
  const [vehiclesReloadKey, setVehiclesReloadKey] = useState(0);

  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [tenureMonths, setTenureMonths] = useState(DEFAULT_TENURE_MONTHS);
  const [mileageBand, setMileageBand] = useState<MileageBand>("standard");
  const mileageBandOptions = useMileageBandOptions();
  const [downpayment, setDownpayment] = useState("");
  // Once the user edits the downpayment themselves, stop overwriting it
  // when the selection changes - only auto-fill a sensible default.
  const [isDownpaymentTouched, setIsDownpaymentTouched] = useState(false);
  // Bumped on every auto-fill - the debounce's resetKey (see below).
  const [downpaymentAutoFillCount, setDownpaymentAutoFillCount] = useState(0);

  const [arena, setArena] = useState<ArenaResult | null>(null);
  const arenaNotOfferedHint = notOfferedHint(...(arena?.results ?? []).map((entry) => entry.comparison?.unavailable));
  const [isArenaLoading, setIsArenaLoading] = useState(false);
  const [arenaError, setArenaError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setIsVehiclesLoading(true);
    setVehiclesError(null);
    // QA audit M23: the picker needs every vehicle to choose from, not
    // just page 1 - see fetchEntireCatalog's own docstring for why
    // looping client-side (rather than a backend page-size override) is
    // the deliberate, scoped-down fix here specifically.
    fetchEntireCatalog(EMPTY_CATALOG_FILTERS)
      .then((results) => {
        if (!cancelled) setVehicles(results);
      })
      .catch(() => {
        if (cancelled) return;
        setVehicles([]);
        setVehiclesError(VEHICLES_LOAD_ERROR);
      })
      .finally(() => {
        if (!cancelled) setIsVehiclesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [vehiclesReloadKey]);

  // Default/auto-fill is the highest min_downpayment among the selected
  // cars (so a shared downpayment satisfies every selected vehicle's own
  // 10% minimum - C6) - a comparison between server-computed values,
  // never a derived money figure.
  useEffect(() => {
    if (isDownpaymentTouched || selectedIds.length === 0) return;
    const selectedVehicles = vehicles.filter((vehicle) => selectedIds.includes(vehicle.id));
    if (selectedVehicles.length === 0) return;
    const highestMinDownpayment = selectedVehicles.reduce((highest, vehicle) =>
      Number(vehicle.min_downpayment) > Number(highest.min_downpayment) ? vehicle : highest,
    );
    setDownpayment(highestMinDownpayment.min_downpayment);
    setDownpaymentAutoFillCount((count) => count + 1);
  }, [selectedIds, vehicles, isDownpaymentTouched]);

  // QA audit M7: only the FETCH below is debounced - validation stays
  // instant (computed off the raw, immediate `downpayment`), since that's
  // cheap client-side work, not a network/ML call.
  //
  // Only TYPING is debounced, though - an auto-fill applies immediately via
  // resetKey (same as ComparisonPage). Without it, picking the 2nd vehicle
  // within 350ms of the 1st fired the arena fetch with the stale debounced
  // downpayment (still "" from before the auto-fill), then fired it again
  // once the debounce settled - the number of requests depended on how
  // fast the clicks were.
  const debouncedDownpayment = useDebouncedValue(downpayment, undefined, downpaymentAutoFillCount);

  const downpaymentNumber = Number(downpayment);
  const downpaymentError =
    downpayment.trim() === ""
      ? "Downpayment is required."
      : Number.isNaN(downpaymentNumber)
        ? "Enter a valid amount."
        : downpaymentNumber < 0
          ? "Downpayment cannot be negative."
          : null;

  const selectionError =
    selectedIds.length < MIN_ARENA_VEHICLES
      ? `Select at least ${MIN_ARENA_VEHICLES} vehicles to compare.`
      : null;

  useEffect(() => {
    if (downpaymentError || selectionError) {
      setArena(null);
      setArenaError(null);
      setIsArenaLoading(false);
      return;
    }
    let cancelled = false;
    setIsArenaLoading(true);
    setArenaError(null);
    fetchArena({ vehicles: selectedIds, tenureMonths, mileageBand, downpayment: debouncedDownpayment })
      .then((data) => {
        if (!cancelled) setArena(data);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setArena(null);
        if (axios.isAxiosError(error) && error.response?.status === 400) {
          setArenaError(parseApiErrorMessage(error.response.data) ?? GENERIC_ERROR);
        } else {
          setArenaError(GENERIC_ERROR);
        }
      })
      .finally(() => {
        if (!cancelled) setIsArenaLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    selectedIds,
    tenureMonths,
    mileageBand,
    debouncedDownpayment,
    downpaymentError,
    selectionError,
  ]);

  const vehiclesById = Object.fromEntries(vehicles.map((vehicle) => [vehicle.id, vehicle]));

  return (
    <div className="mx-auto max-w-6xl px-4 pb-16 pt-8 sm:pt-10">
      <PageHeader
        title="Compare cars"
        subtitle="Pick 2 or 3 cars to see their monthly payments and total cost side by side."
      />

      <div className="mt-6">
        {isVehiclesLoading ? (
          <LoadingSkeleton className="h-40 w-full" />
        ) : vehiclesError ? (
          <div role="alert">
            <EmptyState
              title="Something went wrong"
              description={vehiclesError}
              action={<Button onClick={() => setVehiclesReloadKey((key) => key + 1)}>Try again</Button>}
            />
          </div>
        ) : (
          <VehiclePicker
            vehicles={vehicles}
            selectedIds={selectedIds}
            onChange={setSelectedIds}
            maxSelections={MAX_ARENA_VEHICLES}
          />
        )}
      </div>

      <Card className="mt-6">
        {/* QA audit Cosmetic: see ComparisonPage's own comment - the
            mileage band column gets extra share so its longest label
            doesn't clip. */}
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-[1fr_1.4fr_1fr]">
          <RangeSlider
            label="Tenure"
            value={tenureMonths}
            min={12}
            max={108}
            // QA audit L5: see ComparisonPage's own tenure slider comment.
            step={1}
            formatValue={(v) => `${v} months`}
            onChange={setTenureMonths}
            // FX-2 (item 4): the same ticks as the compare page, and the API's own
            // GFV / Subscription reasons from the Arena response (each said once).
            marks={TENURE_MARKS}
            hint={arenaNotOfferedHint}
          />
          <Select
            label="Mileage band"
            value={mileageBand}
            onChange={(event) => setMileageBand(event.target.value as MileageBand)}
            options={mileageBandOptions}
          />
          <Input
            label="Downpayment (RM)"
            type="number"
            min="0"
            step="0.01"
            value={downpayment}
            onChange={(event) => {
              setIsDownpaymentTouched(true);
              setDownpayment(event.target.value);
            }}
            error={selectionError ? undefined : (downpaymentError ?? undefined)}
          />
        </div>
        {/* Where the downpayment came from. The figure is the auto-filled
            value as the server gave it (a selected car's own min_downpayment) -
            nothing is computed here. Redesign UI-4: one short visible line; the
            full sentence, with the figure, is folded beside it. */}
        {selectedIds.length > 0 && downpayment !== "" && !isDownpaymentTouched && (
          <div className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <p className="text-caption text-ink-muted">Auto-filled with the highest minimum among the selected cars.</p>
            <InfoExpander summary="Why this amount?">
              {`Set to the highest minimum downpayment among the selected cars (${formatCurrency(downpayment)}), so every car is comparable.`}
            </InfoExpander>
          </div>
        )}
        {selectedIds.length > 0 && isDownpaymentTouched && (
          <p className="mt-3 text-caption text-ink-muted">
            You set this manually.{" "}
            <button
              type="button"
              className="font-medium text-primary-700 underline hover:text-primary-800"
              onClick={() => setIsDownpaymentTouched(false)}
            >
              Reset to minimum
            </button>
          </p>
        )}
      </Card>

      <div className="mt-6">
        {selectionError && (
          <EmptyState
            icon={<Columns3 className="h-6 w-6" />}
            title="Select vehicles to compare"
            description={selectionError}
          />
        )}

        {!selectionError && isArenaLoading && (
          <div className="flex flex-col gap-3">
            <LoadingSkeleton className="h-12 w-full" />
            <LoadingSkeleton className="h-12 w-full" />
            <LoadingSkeleton className="h-12 w-full" />
          </div>
        )}

        {!selectionError && !isArenaLoading && arenaError && (
          <EmptyState title="Comparison unavailable" description={arenaError} />
        )}

        {!selectionError && !isArenaLoading && !arenaError && arena && (
          <ArenaTable
            arena={arena}
            vehiclesById={vehiclesById}
            // The inputs this arena was fetched with, so each car's name opens its
            // own compare page on the same three.
            compareInputs={{ tenureMonths, mileageBand, downpayment: debouncedDownpayment }}
          />
        )}
      </div>
    </div>
  );
}
