import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import axios from "axios";
import { ChartLine, ChevronLeft, Layers, Scale, ShieldAlert, Sparkles } from "lucide-react";
import { fetchVehicleDetail } from "../api/catalog";
import { fetchComparison } from "../api/comparisons";
import { fetchFinancialProfile } from "../api/profile";
import { useDebouncedValue } from "../hooks/useDebouncedValue";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { useMileageBandOptions } from "../hooks/useMileageBandOptions";
import { SERVER_UNREACHABLE_MESSAGE, isNotFoundError, parseApiErrorMessage } from "../lib/apiErrors";
import { TENURE_MARKS, notOfferedHint } from "../lib/tenureMarks";
import { DEFAULT_TENURE_MONTHS } from "../lib/defaults";
import {
  DOWNPAYMENT_NOT_BELOW_PRICE_MESSAGE,
  DOWNPAYMENT_OUTRIGHT_MESSAGE,
  downpaymentForVehicle,
  readCompareParams,
  writeCompareParams,
} from "../lib/compareParams";
import type { Vehicle } from "../types/catalog";
import type { ComparisonResult, MileageBand } from "../types/comparisons";
import { mapAnnualMileageBandToMileageBand } from "../types/profile";
import { formatCurrency } from "../lib/formatCurrency";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { Input } from "../components/ui/Input";
import { LoadingSkeleton } from "../components/ui/LoadingSkeleton";
import { PageHeader } from "../components/ui/PageHeader";
import { RangeSlider } from "../components/ui/RangeSlider";
import { Select } from "../components/ui/Select";
import { Tabs } from "../components/ui/Tabs";
import { PathwaysTable } from "../components/comparisons/PathwaysTable";
import { TcoPanel } from "../components/depreciation/TcoPanel";
import { TotalLossSandboxPanel } from "../components/depreciation/TotalLossSandboxPanel";
import { RecommendationPanel } from "../components/scoring/RecommendationPanel";
import { DsrSimulatorPanel } from "../components/scoring/DsrSimulatorPanel";
import { ExportPdfButton } from "../components/exports/ExportPdfButton";
import { Button } from "../components/ui/Button";
import { VehiclePhotoPlaceholder } from "../components/catalog/VehiclePhotoPlaceholder";
import { bodySegmentLabel } from "../lib/vehicleLabels";
import { SaveScenarioButton } from "../components/scenarios/SaveScenarioButton";
import type { ScoringRequestInputs } from "../types/scenarios";
import type { ScoringResult } from "../types/scoring";

// F005 / UC005 - Multi-Pathway Comparison Engine. All calculation
// (steps 1-4 of the use case) happens server-side; this page only
// collects tenure/mileage/downpayment, calls GET /api/comparisons/, and
// renders exactly what comes back. A 400 response is UC005's alternate
// flow (missing/null interest-rate or residual config for this
// brand/tenure/mileage combination) - its `detail` message is shown
// verbatim, not replaced with a generic error.

const GENERIC_ERROR = "Could not calculate this comparison. Please try again.";

export function ComparisonPage() {
  const { id } = useParams<{ id: string }>();
  // Run 1 fix batch 5 (M4): tenure / mileage band / downpayment in the query
  // string, so a refresh or a copied link keeps them. Read once on mount; the
  // URL wins over the profile prefill, which wins over the defaults.
  const [searchParams, setSearchParams] = useSearchParams();
  const [fromUrl] = useState(() => readCompareParams(searchParams));

  const [activeTab, setActiveTab] = useState<
    "financing" | "tco" | "scoring" | "affordability" | "totalLoss"
  >("financing");

  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
  useDocumentTitle(vehicle ? `Compare - ${vehicle.brand_name} ${vehicle.name}` : "Compare Financing Options");
  const [isVehicleLoading, setIsVehicleLoading] = useState(true);
  const [vehicleError, setVehicleError] = useState<string | null>(null);
  const [vehicleErrorIsRetryable, setVehicleErrorIsRetryable] = useState(false);
  const [vehicleReloadKey, setVehicleReloadKey] = useState(0);

  const [tenureMonths, setTenureMonths] = useState(fromUrl.tenureMonths ?? DEFAULT_TENURE_MONTHS);
  const [mileageBand, setMileageBand] = useState<MileageBand>(fromUrl.mileageBand ?? "standard");
  // The one shared mileage-band list (also used by the Financial Profile).
  const mileageBandOptions = useMileageBandOptions();
  const [downpayment, setDownpayment] = useState("");

  const [comparison, setComparison] = useState<ComparisonResult | null>(null);
  const [isComparisonLoading, setIsComparisonLoading] = useState(false);
  const [comparisonError, setComparisonError] = useState<string | null>(null);

  // Lifted out of RecommendationPanel (via its onResult callback): the last
  // scoring result and the request that produced it, set and cleared
  // together. Used only for the "Recommended" badge, and only while that
  // request still matches the current inputs (FX-1 X3, below). The panel
  // still owns its own fetch/loading/error state.
  const [scoring, setScoring] = useState<ScoringResult | null>(null);
  const [scoringRequest, setScoringRequest] = useState<ScoringRequestInputs | null>(null);
  // From the saved profile ("I prefer Islamic financing"): relabels the HP
  // rate as a profit rate. Wording only - never changes a calculation.
  const [prefersIslamicFinancing, setPrefersIslamicFinancing] = useState(false);

  // QA audit M6: the quiz/affordability INPUTS (not just the fetched
  // results above) also live here now, not inside RecommendationPanel/
  // DsrSimulatorPanel's own useState - Tabs.Panel unmounts an inactive
  // tab's component entirely (see components/ui/Tabs.tsx), which wiped
  // these every time the user switched away and back. monthlyIncome/
  // maxDsrPercent are deliberately ONE shared pair of fields, passed to
  // both panels, closing the audit's separate complaint that the AI and
  // Affordability tabs asked for the same two figures independently.
  const [upfrontCashPreservation, setUpfrontCashPreservation] = useState<number | null>(null);
  const [maintenanceProtection, setMaintenanceProtection] = useState<number | null>(null);
  const [ownershipEquity, setOwnershipEquity] = useState<number | null>(null);
  const [monthlyIncome, setMonthlyIncome] = useState("");
  const [maxDsrPercent, setMaxDsrPercent] = useState("");
  const [existingMonthlyCommitments, setExistingMonthlyCommitments] = useState("");

  // FX-1 (X3): the recommendation request for the CURRENT shared ratings,
  // income and Max DSR - what Save sends (the server builds the saved
  // recommendation from it). Null while a rating, the income or the limit is
  // missing, exactly when the AI tab withholds its recommendation. Before,
  // Save sent the last request the AI tab had run, so a Max DSR changed on
  // the Affordability tab afterwards saved a recommendation for the old limit.
  const currentScoringRequest = useMemo<ScoringRequestInputs | null>(() => {
    if (upfrontCashPreservation === null || maintenanceProtection === null || ownershipEquity === null) return null;
    if (monthlyIncome.trim() === "" || maxDsrPercent.trim() === "") return null;
    return {
      upfront_cash_preservation: upfrontCashPreservation,
      maintenance_protection: maintenanceProtection,
      ownership_equity: ownershipEquity,
      monthly_income: monthlyIncome,
      max_dsr_percent: maxDsrPercent,
    };
  }, [upfrontCashPreservation, maintenanceProtection, ownershipEquity, monthlyIncome, maxDsrPercent]);
  // The last scoring result counts only while it was produced for exactly these inputs.
  const scoringIsCurrent =
    scoring !== null &&
    scoringRequest !== null &&
    currentScoringRequest !== null &&
    (Object.keys(currentScoringRequest) as (keyof ScoringRequestInputs)[]).every(
      (key) => currentScoringRequest[key] === scoringRequest[key],
    );

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setIsVehicleLoading(true);
    setVehicleError(null);
    fetchVehicleDetail(id)
      .then((data) => {
        if (cancelled) return;
        setVehicle(data);
        // A link's downpayment if it is usable for this car, else the minimum.
        setDownpayment(downpaymentForVehicle(fromUrl.downpayment, data.min_downpayment, data.msrp));
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // FX-2 (item 1): only a 404 is "not found"; a network failure or 5xx can be retried.
        const notFound = isNotFoundError(err);
        setVehicleError(notFound ? "This vehicle could not be found." : SERVER_UNREACHABLE_MESSAGE);
        setVehicleErrorIsRetryable(!notFound);
      })
      .finally(() => {
        if (!cancelled) setIsVehicleLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id, vehicleReloadKey]);

  // Batch 6C / Part 1c: prefill tenure/mileage from the user's saved UC003
  // baseline, if they have one - closes the QA audit's original "saved
  // baseline is never read by anything" finding. Deliberately independent
  // of the vehicle-detail effect above and run ONCE on mount (empty
  // dependency array): this only ever sets the two fields' INITIAL
  // values - re-running it on every vehicle/id change would silently
  // stomp a tenure/mileage band the user has since adjusted away from
  // the prefilled baseline on their own.
  useEffect(() => {
    let cancelled = false;
    fetchFinancialProfile()
      .then((profile) => {
        if (cancelled || !profile) return;
        // A value from the link wins over the profile's.
        if (fromUrl.tenureMonths === null) setTenureMonths(profile.preferred_tenure_months);
        if (fromUrl.mileageBand === null) {
          setMileageBand(mapAnnualMileageBandToMileageBand(profile.annual_mileage_band));
        }
        setPrefersIslamicFinancing(profile.shariah_compliant_required);
        // Run 1 fix batch 5 (A5): start the AI Recommendation / Affordability
        // inputs from the profile - only if the buyer hasn't typed one yet.
        if (profile.monthly_income) setMonthlyIncome((prev) => (prev === "" ? profile.monthly_income ?? "" : prev));
        if (profile.max_dsr_percent) setMaxDsrPercent((prev) => (prev === "" ? profile.max_dsr_percent ?? "" : prev));
      })
      .catch(() => {
        // Silent - this is a convenience prefill, never a blocking error.
        // The shared defaults (DEFAULT_TENURE_MONTHS / "standard") stand if this fails.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // QA audit M7: every panel below (and the comparison fetch in this
  // page itself) runs a real calculation/ML-touching request on every
  // downpayment change - debounce the VALUE those fetches see, not the
  // <Input> itself (which stays bound to the raw, immediate state so
  // typing feels instant, same as validation below).
  const debouncedDownpayment = useDebouncedValue(downpayment, undefined, vehicle?.id);

  // Keep the query string in step with the inputs (replace, not push: the
  // Back button still leaves the page in one step).
  useEffect(() => {
    if (!vehicle) return;
    setSearchParams(
      (prev) => writeCompareParams(prev, { tenureMonths, mileageBand, downpayment: debouncedDownpayment }),
      { replace: true },
    );
  }, [vehicle, tenureMonths, mileageBand, debouncedDownpayment, setSearchParams]);

  const msrp = vehicle ? Number(vehicle.msrp) : null;
  const downpaymentNumber = Number(downpayment);
  const downpaymentError =
    downpayment.trim() === ""
      ? "Downpayment is required."
      : Number.isNaN(downpaymentNumber)
        ? "Enter a valid amount."
        : downpaymentNumber < 0
          ? "Downpayment cannot be negative."
          : msrp !== null && downpaymentNumber === msrp
            ? DOWNPAYMENT_OUTRIGHT_MESSAGE // FX-2 (item 5): exactly the price - a cash purchase
            : msrp !== null && downpaymentNumber > msrp
            ? DOWNPAYMENT_NOT_BELOW_PRICE_MESSAGE // the API's sentence, word for word (F-30c)
            : vehicle && downpaymentNumber < Number(vehicle.min_downpayment)
              ? `Minimum downpayment is 10% of the vehicle price (${formatCurrency(vehicle.min_downpayment)}).`
              : null;

  useEffect(() => {
    if (!vehicle) return;
    // QA audit H14: null out comparison/tco/scoring IMMEDIATELY, before
    // the new fetch even starts - not just on an error. Previously
    // `comparison` (and tco/scoring, via each panel's own onResult) kept
    // their OLD values live for the whole window between an input change
    // and the new fetch resolving, and Save/Export only gated on
    // `comparison` being non-null - so a user who changed the tenure
    // slider and immediately clicked Save/Export during that window got
    // the old comparison (and whatever stale tco/scoring happened to be
    // in state) saved under the NEW tenure header. Nulling here means
    // Save/Export (both gated on `comparison`) are disabled for exactly
    // the window where the current inputs don't have a matching result
    // yet, with no separate "is this stale" flag required.
    setComparison(null);
    setScoring(null);
    setScoringRequest(null);
    if (downpaymentError) {
      // Invalid input: don't call the API (the Input's own error message
      // is the feedback).
      setComparisonError(null);
      setIsComparisonLoading(false);
      return;
    }
    let cancelled = false;
    setIsComparisonLoading(true);
    setComparisonError(null);
    fetchComparison({ vehicle: vehicle.id, tenureMonths, mileageBand, downpayment: debouncedDownpayment })
      .then((data) => {
        if (!cancelled) setComparison(data);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setComparison(null);
        if (axios.isAxiosError(error) && error.response?.status === 400) {
          setComparisonError(parseApiErrorMessage(error.response.data) ?? GENERIC_ERROR);
        } else {
          setComparisonError(GENERIC_ERROR);
        }
      })
      .finally(() => {
        if (!cancelled) setIsComparisonLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [vehicle, tenureMonths, mileageBand, debouncedDownpayment, downpaymentError]);

  if (isVehicleLoading) {
    return (
      <div className="mx-auto mt-10 max-w-5xl px-4">
        <LoadingSkeleton variant="text" className="w-48" />
        <LoadingSkeleton className="mt-4 h-40 w-full" />
      </div>
    );
  }

  if (vehicleError || !vehicle) {
    return (
      <div className="mx-auto mt-10 max-w-5xl px-4">
        <EmptyState
          title={vehicleErrorIsRetryable ? "Server unavailable" : "Vehicle not found"}
          description={vehicleError ?? undefined}
          action={
            vehicleErrorIsRetryable ? (
              <Button onClick={() => setVehicleReloadKey((key) => key + 1)}>Try again</Button>
            ) : undefined
          }
        />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl px-4 pb-16 pt-8 sm:pt-10">
      <div className="flex items-start gap-4">
        {/* A small 4:3 picture of the car (its photo, or the placeholder), from sm up. */}
        <div className="hidden aspect-[4/3] w-28 shrink-0 overflow-hidden rounded-control border border-border bg-surface-subtle sm:block">
          {vehicle.thumbnail_url ? (
            <img src={vehicle.thumbnail_url} alt={`${vehicle.brand_name} ${vehicle.name}`} className="h-full w-full object-cover" />
          ) : (
            <VehiclePhotoPlaceholder brandName={vehicle.brand_name} modelName={vehicle.name} segmentLabel={bodySegmentLabel(vehicle.body_segment)} />
          )}
        </div>
        <PageHeader
          className="min-w-0 flex-1"
          breadcrumb={
            <Link
              to={`/catalog/${vehicle.id}`}
              className="inline-flex items-center gap-1 rounded-control font-medium text-ink-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
            >
              <ChevronLeft className="h-4 w-4" aria-hidden="true" />
              Back to {vehicle.name} {vehicle.trim}
            </Link>
          }
          title="Compare Financing Options"
          subtitle={`${vehicle.brand_name} ${vehicle.name} ${vehicle.trim} · ${formatCurrency(vehicle.msrp)}`}
          actions={
            <>
          <SaveScenarioButton
            vehicleId={vehicle.id}
            comparison={comparison}
            scoringRequest={currentScoringRequest}
            tenureMonths={tenureMonths}
            mileageBand={mileageBand}
            downpayment={debouncedDownpayment}
          />
          <ExportPdfButton
            vehicleId={vehicle.id}
            comparison={comparison}
            tenureMonths={tenureMonths}
            mileageBand={mileageBand}
            downpayment={debouncedDownpayment}
          />
            </>
          }
        />
      </div>

      <Card className="mt-6">
        {/* QA audit Cosmetic: the mileage band dropdown's longest label
            (a band name plus its km range) clipped mid-word inside
            an EQUAL one-third column - its own column gets more share
            than Tenure/Downpayment need, rather than shortening the
            label text (which must keep matching the backend's own
            MileageBand choices exactly - see QA audit M11). */}
        <div className="grid grid-cols-1 gap-6 sm:grid-cols-[1fr_1.4fr_1fr]">
          <RangeSlider
            label="Tenure"
            value={tenureMonths}
            min={12}
            max={108}
            // QA audit L5: UC005/UC006 allow any integer month 12-108,
            // not just 12-month steps - the backend's own tenure
            // validators (MIN/MAX_TENURE_MONTHS) never enforced a
            // 12-multiple constraint, only this slider's step did.
            step={1}
            formatValue={(v) => `${v} months`}
            onChange={setTenureMonths}
            // FX-2 (item 4): ticks at the terms every option shares, and the API's
            // own reasons when GFV or Subscription is not offered for these inputs.
            marks={TENURE_MARKS}
            hint={notOfferedHint(comparison?.unavailable)}
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
            onChange={(event) => setDownpayment(event.target.value)}
            error={downpaymentError ?? undefined}
          />
        </div>
      </Card>

      <Tabs
        value={activeTab}
        onChange={(value) =>
          setActiveTab(value as "financing" | "tco" | "scoring" | "affordability" | "totalLoss")
        }
        className="mt-6"
      >
        {/* Redesign UI-6c: below sm, a "View" select instead of the sideways-scrolling strip. */}
        <Tabs.List aria-label="Comparison views" mobileSelectLabel="View">
          {/* Redesign UI-3: shorter labels, each with an icon (the panels, values
              and state behind them are unchanged). UI-6c: the icons show from lg,
              so the five tabs fit the strip from 640 px up without scrolling. */}
          <Tabs.Tab value="financing">
            <Layers className="mr-1.5 hidden h-4 w-4 align-[-3px] lg:inline" aria-hidden="true" />
            Financing options
          </Tabs.Tab>
          <Tabs.Tab value="tco">
            <ChartLine className="mr-1.5 hidden h-4 w-4 align-[-3px] lg:inline" aria-hidden="true" />
            Total cost
          </Tabs.Tab>
          <Tabs.Tab value="scoring">
            <Sparkles className="mr-1.5 hidden h-4 w-4 align-[-3px] lg:inline" aria-hidden="true" />
            AI recommendation
          </Tabs.Tab>
          <Tabs.Tab value="affordability">
            <Scale className="mr-1.5 hidden h-4 w-4 align-[-3px] lg:inline" aria-hidden="true" />
            Affordability
          </Tabs.Tab>
          <Tabs.Tab value="totalLoss">
            <ShieldAlert className="mr-1.5 hidden h-4 w-4 align-[-3px] lg:inline" aria-hidden="true" />
            If written off
          </Tabs.Tab>
        </Tabs.List>

        <Tabs.Panel value="financing" className="mt-6">
          {isComparisonLoading && (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
              <LoadingSkeleton className="h-56 w-full" />
              <LoadingSkeleton className="h-56 w-full" />
              <LoadingSkeleton className="h-56 w-full" />
            </div>
          )}

          {!isComparisonLoading && comparisonError && (
            <EmptyState title="Comparison unavailable" description={comparisonError} />
          )}

          {!isComparisonLoading && !comparisonError && comparison && (
            <PathwaysTable
              comparison={comparison}
              prefersIslamicFinancing={prefersIslamicFinancing}
              // "Recommended" only from the scoring API's own result, when the AI
              // tab has produced one for these exact inputs - never inferred here
              // (FX-1 X3: not after the Max DSR, income or a rating changed since).
              recommendedPathway={scoringIsCurrent ? scoring!.recommended_pathway : null}
              onRatePriorities={() => setActiveTab("scoring")}
            />
          )}
        </Tabs.Panel>

        <Tabs.Panel value="tco" className="mt-6">
          <TcoPanel
            vehicleId={vehicle.id}
            tenureMonths={tenureMonths}
            mileageBand={mileageBand}
            downpayment={debouncedDownpayment}
            downpaymentError={downpaymentError}
          />
        </Tabs.Panel>

        <Tabs.Panel value="scoring" className="mt-6">
          <RecommendationPanel
            vehicleId={vehicle.id}
            tenureMonths={tenureMonths}
            mileageBand={mileageBand}
            downpayment={debouncedDownpayment}
            downpaymentError={downpaymentError}
            upfrontCashPreservation={upfrontCashPreservation}
            onUpfrontCashPreservationChange={setUpfrontCashPreservation}
            maintenanceProtection={maintenanceProtection}
            onMaintenanceProtectionChange={setMaintenanceProtection}
            ownershipEquity={ownershipEquity}
            onOwnershipEquityChange={setOwnershipEquity}
            monthlyIncome={monthlyIncome}
            onMonthlyIncomeChange={setMonthlyIncome}
            maxDsrPercent={maxDsrPercent}
            onMaxDsrPercentChange={setMaxDsrPercent}
            onResult={(result, request) => {
              setScoring(result);
              setScoringRequest(request);
            }}
          />
        </Tabs.Panel>

        <Tabs.Panel value="affordability" className="mt-6">
          <DsrSimulatorPanel
            vehicleId={vehicle.id}
            tenureMonths={tenureMonths}
            mileageBand={mileageBand}
            downpayment={debouncedDownpayment}
            downpaymentError={downpaymentError}
            monthlyIncome={monthlyIncome}
            onMonthlyIncomeChange={setMonthlyIncome}
            maxDsrPercent={maxDsrPercent}
            onMaxDsrPercentChange={setMaxDsrPercent}
            existingMonthlyCommitments={existingMonthlyCommitments}
            onExistingMonthlyCommitmentsChange={setExistingMonthlyCommitments}
          />
        </Tabs.Panel>

        <Tabs.Panel value="totalLoss" className="mt-6">
          <TotalLossSandboxPanel
            vehicleId={vehicle.id}
            tenureMonths={tenureMonths}
            mileageBand={mileageBand}
            downpayment={debouncedDownpayment}
            downpaymentError={downpaymentError}
          />
        </Tabs.Panel>
      </Tabs>
    </div>
  );
}
