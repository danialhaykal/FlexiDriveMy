import { useEffect, useState } from "react";
import axios from "axios";
import { fetchTotalLossSandbox } from "../../api/depreciation";
import { useDebouncedValue } from "../../hooks/useDebouncedValue";
import { parseApiErrorMessage } from "../../lib/apiErrors";
import type { MileageBand } from "../../types/comparisons";
import { PATHWAY_LABELS } from "../../types/scoring";
import type { PathwayKey } from "../../types/scoring";
import type { TotalLossSandboxPathway, TotalLossSandboxResult } from "../../types/totalLossSandbox";
import { formatCurrency } from "../../lib/formatCurrency";
import { Badge } from "../ui/Badge";
import { Card } from "../ui/Card";
import { InfoExpander } from "../ui/InfoExpander";
import { cn } from "../ui/cn";
import { EmptyState } from "../ui/EmptyState";
import { Input } from "../ui/Input";
import { LoadingSkeleton } from "../ui/LoadingSkeleton";
import { RangeSlider } from "../ui/RangeSlider";

// Sprint 12 - illustrative Total-Loss Exposure Sandbox. Separate tool
// from F006's own TCO tab: it doesn't chart the 60-month curve, it asks
// "what if this vehicle were written off in the month you pick" and
// shows the same three numbers (insurance payout, outstanding balance,
// net position) across all three pathways. Reuses F006's real ML resale
// curve/HP formula and F005's GFV residual lookup - no new ML, no new
// financing math (see apps/depreciation/services.py::build_total_loss_sandbox).
//
// This is illustrative only, not real insurance data - see the
// disclaimer below, which must stay accurate (never imply a real bureau
// or insurer check).

interface TotalLossSandboxPanelProps {
  vehicleId: number;
  tenureMonths: number;
  mileageBand: MileageBand;
  downpayment: string;
  downpaymentError: string | null;
}

const GENERIC_ERROR = "Could not calculate this total-loss scenario. Please try again.";
const PATHWAY_DOT: Record<PathwayKey, string> = {
  hire_purchase: "bg-pathway-hp",
  gfv_leasing: "bg-pathway-gfv",
  subscription: "bg-pathway-sub",
};
const PATHWAY_ORDER: PathwayKey[] = ["hire_purchase", "gfv_leasing", "subscription"];

function formatSignedCurrency(value: string): { text: string; toneClass: string } {
  const amount = Number(value);
  const isPositive = amount >= 0;
  return {
    text: `${isPositive ? "+" : "-"}${formatCurrency(String(Math.abs(amount)))}`,
    toneClass: isPositive ? "text-positive-700" : "text-danger-700",
  };
}

// FX-2 (item 12): how long the month slider must rest before the sandbox is asked.
export const SANDBOX_DEBOUNCE_MS = 250;

export function TotalLossSandboxPanel({
  vehicleId,
  tenureMonths,
  mileageBand,
  downpayment,
  downpaymentError,
}: TotalLossSandboxPanelProps) {
  // QA audit L8: defaults to the midpoint of the term rather than month
  // 0 - a more representative "what if" starting point than the very
  // first month, when the loan balance is at its highest and least
  // interesting to inspect. Lazy initializer: a one-time default from
  // the tenure at mount, not re-applied on every tenureMonths change
  // (effectiveLossMonth below already clamps if tenure later shrinks
  // below whatever the user has picked).
  const [lossMonth, setLossMonth] = useState(() => Math.floor(tenureMonths / 2));
  const [excessAmount, setExcessAmount] = useState("");

  const [result, setResult] = useState<TotalLossSandboxResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // tenureMonths can change (the shared slider on ComparisonPage) after
  // lossMonth was already set higher - clamp rather than let a stale
  // value briefly exceed the new tenure.
  // Run 1 fix batch 5 (X3): month 0 (before the first instalment) isn't a
  // choice - the API refuses it ("Choose a month from 1 to {tenure}.") and the
  // slider starts at 1.
  const effectiveLossMonth = Math.max(1, Math.min(lossMonth, tenureMonths));
  // FX-2 (item 12, R4-P7-01): the request waits until the slider has rested for
  // SANDBOX_DEBOUNCE_MS (holding an arrow key sent one request per step); the
  // "Month N" label above still follows every step at once. While a month is
  // waiting, the cards show the loading state, never the previous month's figures.
  const requestedLossMonth = useDebouncedValue(effectiveLossMonth, SANDBOX_DEBOUNCE_MS);
  const isWaitingForMonth = requestedLossMonth !== effectiveLossMonth;

  useEffect(() => {
    if (downpaymentError) {
      setResult(null);
      setError(null);
      setIsLoading(false);
      return;
    }
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    fetchTotalLossSandbox({
      vehicle: vehicleId,
      tenureMonths,
      mileageBand,
      downpayment,
      lossMonth: requestedLossMonth,
      excessAmount: excessAmount.trim() === "" ? "0" : excessAmount,
    })
      .then((data) => {
        if (!cancelled) setResult(data);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setResult(null);
        if (axios.isAxiosError(err) && err.response?.status === 400) {
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
  }, [vehicleId, tenureMonths, mileageBand, downpayment, downpaymentError, requestedLossMonth, excessAmount]);

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <h2 className="text-h3 font-semibold text-ink">Total-loss scenario</h2>
        <p className="mt-1 text-small text-ink-muted">
          Pick a month and see what each pathway would look like if the vehicle were written off then.
        </p>
        {/* Redesign UI-3: one visible line; the rest of the caveat one click away. */}
        <div className="mt-3 rounded-control border border-warning-200 bg-warning-50 p-3">
          <p className="text-caption font-medium text-warning-700">
            Illustrative only: assumes a comprehensive insurance payout equal to predicted market value at
            the month you choose, less your declared excess.
          </p>
          <InfoExpander summary="More about this estimate" className="mt-1 text-caption">
            <p className="text-warning-700">
              Real claims settlements can differ. FlexiDriveMy does not decide when a vehicle is a total loss.
            </p>
          </InfoExpander>
        </div>
        <div className="mt-4 grid grid-cols-1 gap-6 sm:grid-cols-2">
          <RangeSlider
            label="Month of loss"
            value={effectiveLossMonth}
            min={1}
            max={tenureMonths}
            step={1}
            formatValue={(v) => `Month ${v}`}
            onChange={setLossMonth}
          />
          <Input
            label="Your policy excess (RM)"
            type="number"
            min="0"
            step="0.01"
            value={excessAmount}
            onChange={(event) => setExcessAmount(event.target.value)}
          />
        </div>
      </Card>

      {(isLoading || isWaitingForMonth) && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <LoadingSkeleton className="h-40 w-full" />
          <LoadingSkeleton className="h-40 w-full" />
          <LoadingSkeleton className="h-40 w-full" />
        </div>
      )}

      {!isLoading && !isWaitingForMonth && !downpaymentError && error && (
        <EmptyState title="Total-loss scenario unavailable" description={error} />
      )}

      {!isLoading && !isWaitingForMonth && !downpaymentError && !error && result && (
        <div className="flex flex-col gap-4">
          {result.model_degraded && result.degraded_reason && (
            <p className="rounded-control border border-warning-200 bg-warning-50 p-3 text-small text-warning-700">
              {result.degraded_reason}
            </p>
          )}

          {result.resale_value_is_plateaued && (
            <p className="rounded-control border border-warning-200 bg-warning-50 p-3 text-small text-warning-700">
              Month {result.loss_month} is beyond this model's 60-month forecast horizon - the resale
              value used here is carried over from month 60, not a genuine prediction for this month.
            </p>
          )}

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            {PATHWAY_ORDER.map((pathwayKey) => {
              const pathway: TotalLossSandboxPathway | null = result[pathwayKey];

              if (!pathway) {
                return (
                  <Card key={pathwayKey} className="bg-page-bg shadow-none">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h3 className="text-[1rem] font-bold text-ink-muted">{PATHWAY_LABELS[pathwayKey]}</h3>
                      <Badge tone="danger">Not available</Badge>
                    </div>
                    <p className="mt-2 text-small text-ink-muted">{result.unavailable[pathwayKey]}</p>
                  </Card>
                );
              }

              // The sign and the colour come from the API's own net position.
              const netPosition = pathway.net_position !== null ? formatSignedCurrency(pathway.net_position) : null;
              return (
                <Card key={pathwayKey} className="flex flex-col gap-4">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <h3 className="flex items-center gap-2 text-[1rem] font-bold text-ink">
                      <span className={cn("h-2.5 w-2.5 shrink-0 rounded-[3px]", PATHWAY_DOT[pathwayKey])} aria-hidden="true" />
                      {PATHWAY_LABELS[pathwayKey]}
                    </h3>
                    {pathway.has_ownership_exposure ? (
                      <Badge tone="neutral">Ownership exposure</Badge>
                    ) : (
                      <Badge tone="positive">No ownership exposure</Badge>
                    )}
                  </div>

                  <dl className="flex flex-col gap-3">
                    <div>
                      <dt className="text-[0.6875rem] font-semibold uppercase tracking-[0.06em] text-ink-muted">Net position</dt>
                      <dd
                        className={
                          netPosition
                            ? `mt-1 text-money-sm font-bold tracking-tight tabular-nums ${netPosition.toneClass}`
                            : "mt-1 text-small font-medium text-ink-subtle"
                        }
                      >
                        {netPosition ? netPosition.text : "Not applicable"}
                      </dd>
                    </div>
                    <div className="grid grid-cols-2 gap-x-4 gap-y-3 border-t border-border pt-3">
                      <div className="min-w-0">
                        <dt className="text-caption font-semibold text-ink-muted">Insurance payout</dt>
                        <dd className="mt-0.5 text-small font-semibold tabular-nums text-ink">
                          {pathway.insurance_payout !== null ? (
                            formatCurrency(pathway.insurance_payout)
                          ) : (
                            <span className="font-normal text-ink-subtle">Not applicable - no ownership stake</span>
                          )}
                        </dd>
                      </div>
                      <div className="min-w-0">
                        <dt className="text-caption font-semibold text-ink-muted">Amount to settle (estimate)</dt>
                        <dd className="mt-0.5 text-small font-semibold tabular-nums text-ink">
                          {pathway.outstanding_balance !== null ? (
                            formatCurrency(pathway.outstanding_balance)
                          ) : (
                            <span className="font-normal text-ink-subtle">Not applicable - no ownership stake</span>
                          )}
                        </dd>
                      </div>
                    </div>
                  </dl>
                </Card>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
