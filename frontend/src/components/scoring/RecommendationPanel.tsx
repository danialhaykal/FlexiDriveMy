import { useEffect, useState } from "react";
import axios from "axios";
import { fetchScoring } from "../../api/scoring";
import { parseApiErrorMessage } from "../../lib/apiErrors";
import type { MileageBand } from "../../types/comparisons";
import type { ScoringRequestInputs } from "../../types/scenarios";
import type { ScoringResult } from "../../types/scoring";
import { Card } from "../ui/Card";
import { EmptyState } from "../ui/EmptyState";
import { Input } from "../ui/Input";
import { LoadingSkeleton } from "../ui/LoadingSkeleton";
import { RangeSlider } from "../ui/RangeSlider";
import { ScoringResultView } from "./ScoringResultView";

// F007 / UC007 "AI Recommendation" tab. Fetches GET /api/scoring/ once
// the lifestyle quiz (3 priority ratings + monthly income + max DSR
// limit) is fully answered, and whenever it or the shared
// tenure/mileage/downpayment inputs change. Mounting only while this tab
// is selected (see Tabs.Panel) is what keeps this from being called up
// front alongside F005/F006's endpoints.

interface RecommendationPanelProps {
  vehicleId: number;
  tenureMonths: number;
  mileageBand: MileageBand;
  downpayment: string;
  downpaymentError: string | null;
  // QA audit M6: the quiz inputs (ratings, income, DSR limit) now live in
  // ComparisonPage, not this panel's own useState - Tabs.Panel unmounts
  // this component entirely while another tab is active (see
  // components/ui/Tabs.tsx), so local state was wiped on every tab
  // switch. Lifting it up means the VALUES survive unmount/remount, while
  // the fetch itself still only runs while this panel is mounted - the
  // lazy-fetch property TcoPanel's own comment already documents is
  // unchanged. income/maxDsrPercent are shared with DsrSimulatorPanel
  // (same QA audit: "the AI and Affordability tabs ask for the same
  // income and DSR separately") - both panels read/write the SAME parent
  // state now, so entering one updates the other on its next mount.
  upfrontCashPreservation: number | null;
  onUpfrontCashPreservationChange: (value: number | null) => void;
  maintenanceProtection: number | null;
  onMaintenanceProtectionChange: (value: number | null) => void;
  ownershipEquity: number | null;
  onOwnershipEquityChange: (value: number | null) => void;
  monthlyIncome: string;
  onMonthlyIncomeChange: (value: string) => void;
  maxDsrPercent: string;
  onMaxDsrPercentChange: (value: string) => void;
  // Reports the latest successfully-loaded result up to the parent, with
  // the request that produced it (ComparisonPage hands that request to
  // "Save this Comparison", whose server-built snapshot re-runs it) - not
  // used for rendering here. Both are null when there is no result.
  onResult?: (result: ScoringResult | null, request: ScoringRequestInputs | null) => void;
}

const GENERIC_ERROR = "Could not calculate a recommendation. Please try again.";

export function RecommendationPanel({
  vehicleId,
  tenureMonths,
  mileageBand,
  downpayment,
  downpaymentError,
  upfrontCashPreservation,
  onUpfrontCashPreservationChange,
  maintenanceProtection,
  onMaintenanceProtectionChange,
  ownershipEquity,
  onOwnershipEquityChange,
  monthlyIncome,
  onMonthlyIncomeChange,
  maxDsrPercent,
  onMaxDsrPercentChange,
  onResult,
}: RecommendationPanelProps) {
  const [result, setResult] = useState<ScoringResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Names the priorities the buyer hasn't rated yet (shown under the sliders).
  const unratedPriorities = [
    upfrontCashPreservation === null ? "Upfront cash preservation" : null,
    maintenanceProtection === null ? "Maintenance protection" : null,
    ownershipEquity === null ? "Ownership equity" : null,
  ].filter((name): name is string => name !== null);

  // Mirrors the recommendation's alternate flow client-side: block scoring (and show
  // its exact copy) while any priority is unrated. Income/DSR are also
  // required by the API but aren't part of that use-case's own alternate
  // flow, so an unrelated blank-field prompt covers those instead.
  const quizIncompleteMessage =
    upfrontCashPreservation === null || maintenanceProtection === null || ownershipEquity === null
      ? "Please rate all three priorities to receive a recommendation."
      : monthlyIncome.trim() === "" || maxDsrPercent.trim() === ""
        ? "Enter your monthly income and maximum DSR limit to see a recommendation."
        : null;

  useEffect(() => {
    if (downpaymentError || quizIncompleteMessage) {
      setResult(null);
      // Nothing is on screen now, so nothing from this tab may be saved.
      onResult?.(null, null);
      setError(null);
      setIsLoading(false);
      return;
    }
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    // Non-null: quizIncompleteMessage is only null once all three are set
    // (see its definition above) - the guard clause above already
    // returned otherwise, TS just can't trace that through a separately
    // derived string.
    const request: ScoringRequestInputs = {
      upfront_cash_preservation: upfrontCashPreservation!,
      maintenance_protection: maintenanceProtection!,
      ownership_equity: ownershipEquity!,
      monthly_income: monthlyIncome,
      max_dsr_percent: maxDsrPercent,
    };
    fetchScoring({
      vehicle: vehicleId,
      tenureMonths,
      mileageBand,
      downpayment,
      upfrontCashPreservation: request.upfront_cash_preservation,
      maintenanceProtection: request.maintenance_protection,
      ownershipEquity: request.ownership_equity,
      monthlyIncome: request.monthly_income,
      maxDsrPercent: request.max_dsr_percent,
    })
      .then((data) => {
        if (cancelled) return;
        setResult(data);
        onResult?.(data, request);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setResult(null);
        onResult?.(null, null);
        if (axios.isAxiosError(err) && err.response?.status === 400) {
          // QA audit M13: previously only checked .priorities/.downpayment/
          // .detail by name - a 400 on monthly_income or max_dsr_percent
          // (0, negative, out of range) fell through to the generic
          // message even though DRF already returned a specific one.
          setError(parseApiErrorMessage(err.response.data) ?? GENERIC_ERROR);
        } else {
          setError(GENERIC_ERROR);
        }
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    vehicleId,
    tenureMonths,
    mileageBand,
    downpayment,
    downpaymentError,
    upfrontCashPreservation,
    maintenanceProtection,
    ownershipEquity,
    monthlyIncome,
    maxDsrPercent,
    quizIncompleteMessage,
  ]);

  return (
    <div className="flex flex-col gap-6">
      {/* Redesign UI-3: two clear groups, "Your priorities" and "Your budget";
          the sliders' unrated state, helper text and withheld message are unchanged. */}
      <Card>
        <section aria-labelledby="ai-priorities-heading">
        <h2 id="ai-priorities-heading" className="text-h3 font-semibold text-ink">Your priorities</h2>
        <p className="mt-1 text-small text-ink-muted">
          Drag each slider to rate how much it matters to you (1 = not important, 5 = very important).
        </p>
        {/* An unrated slider shows NO number (value stays null): what the
            screen shows is exactly what is sent, never a pre-selected 3. */}
        <div className="mt-4 grid grid-cols-1 gap-6 sm:grid-cols-3">
          <RangeSlider
            label="Upfront cash preservation"
            min={1}
            max={5}
            step={1}
            value={upfrontCashPreservation}
            onChange={onUpfrontCashPreservationChange}
          />
          <RangeSlider
            label="Maintenance protection"
            min={1}
            max={5}
            step={1}
            value={maintenanceProtection}
            onChange={onMaintenanceProtectionChange}
          />
          <RangeSlider
            label="Ownership equity"
            min={1}
            max={5}
            step={1}
            value={ownershipEquity}
            onChange={onOwnershipEquityChange}
          />
        </div>
        {unratedPriorities.length > 0 && (
          <p className="mt-3 text-small text-ink-muted">
            Still to rate: {unratedPriorities.join(", ")}.
          </p>
        )}
        </section>
        <section aria-labelledby="ai-budget-heading" className="mt-6 border-t border-border pt-5">
        <h2 id="ai-budget-heading" className="text-h3 font-semibold text-ink">Your budget</h2>
        <p className="mt-1 text-small text-ink-muted">Used to check each option against your debt service ratio (DSR) limit.</p>
        <div className="mt-4 grid grid-cols-1 gap-6 sm:grid-cols-2">
          <Input
            // FX-2 (item 7): gross income, before tax (DSR is measured on gross income).
            label="Monthly income (gross, RM)"
            type="number"
            min="0"
            step="0.01"
            value={monthlyIncome}
            onChange={(event) => onMonthlyIncomeChange(event.target.value)}
          />
          <Input
            label="Max DSR limit (%)"
            type="number"
            min="1"
            max="100"
            step="0.01"
            value={maxDsrPercent}
            onChange={(event) => onMaxDsrPercentChange(event.target.value)}
          />
        </div>
        </section>
      </Card>

      {isLoading && (
        <div className="flex flex-col gap-3">
          <LoadingSkeleton className="h-24 w-full" />
          <LoadingSkeleton className="h-24 w-full" />
          <LoadingSkeleton className="h-24 w-full" />
        </div>
      )}

      {!isLoading && !downpaymentError && quizIncompleteMessage && (
        <EmptyState
          title="Complete the quiz to see a recommendation"
          description={quizIncompleteMessage}
        />
      )}

      {!isLoading && !downpaymentError && !quizIncompleteMessage && error && (
        <EmptyState title="Recommendation unavailable" description={error} />
      )}

      {!isLoading && !downpaymentError && !quizIncompleteMessage && !error && result && (
        <ScoringResultView result={result} />
      )}
    </div>
  );
}
