import { useEffect, useState } from "react";
import axios from "axios";
import { fetchDsrSimulator } from "../../api/scoring";
import { parseApiErrorMessage } from "../../lib/apiErrors";
import type { MileageBand } from "../../types/comparisons";
import { PATHWAY_LABELS } from "../../types/scoring";
import type { PathwayKey } from "../../types/scoring";
import type { DsrSimulatorResult } from "../../types/dsrSimulator";
import { formatCurrency, formatPercent } from "../../lib/formatCurrency";
import { cn } from "../ui/cn";
import { Badge } from "../ui/Badge";
import { InfoExpander } from "../ui/InfoExpander";
import { Card } from "../ui/Card";
import { EmptyState } from "../ui/EmptyState";
import { Input } from "../ui/Input";
import { LoadingSkeleton } from "../ui/LoadingSkeleton";

// Sprint 11 - standalone Affordability / DSR Simulator (FYP1's "CCRIS
// Credit Damage" capability). Separate tool from F007's own AI
// Recommendation tab: it doesn't rank or recommend anything, it only
// reports each pathway's total DSR (this instalment plus whatever other
// debt the user has already declared) and whether that pathway is a real
// credit agreement reported to CCRIS. Self-declared inputs only - see the
// caption below, which must stay true: this never claims a live bureau
// check.

interface DsrSimulatorPanelProps {
  vehicleId: number;
  tenureMonths: number;
  mileageBand: MileageBand;
  downpayment: string;
  downpaymentError: string | null;
  // QA audit M6: lifted to ComparisonPage so the values survive this
  // panel unmounting on a tab switch (see RecommendationPanel's own
  // comment on the same props) - monthlyIncome/maxDsrPercent are the SAME
  // state RecommendationPanel reads/writes, closing the audit's separate
  // complaint that the AI and Affordability tabs asked for the same two
  // figures independently.
  monthlyIncome: string;
  onMonthlyIncomeChange: (value: string) => void;
  maxDsrPercent: string;
  onMaxDsrPercentChange: (value: string) => void;
  existingMonthlyCommitments: string;
  onExistingMonthlyCommitmentsChange: (value: string) => void;
}

const GENERIC_ERROR = "Could not calculate this affordability simulation. Please try again.";
const PATHWAY_ORDER: PathwayKey[] = ["hire_purchase", "gfv_leasing", "subscription"];

const PATHWAY_DOT: Record<PathwayKey, string> = {
  hire_purchase: "bg-pathway-hp",
  gfv_leasing: "bg-pathway-gfv",
  subscription: "bg-pathway-sub",
};

// Redesign UI-3: the bar is drawn on a 0-100% of income scale. Its fill width
// is the API's total DSR % and the marker sits at the buyer's Max DSR limit,
// both used as CSS percentages exactly as sent (a DSR over 100% is simply
// clipped by the track) - no arithmetic. The colour follows ONLY the API's
// exceeds_dsr: positive within the limit, danger over it.

export function DsrSimulatorPanel({
  vehicleId,
  tenureMonths,
  mileageBand,
  downpayment,
  downpaymentError,
  monthlyIncome,
  onMonthlyIncomeChange,
  maxDsrPercent,
  onMaxDsrPercentChange,
  existingMonthlyCommitments,
  onExistingMonthlyCommitmentsChange,
}: DsrSimulatorPanelProps) {
  const [result, setResult] = useState<DsrSimulatorResult | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const inputsIncompleteMessage =
    monthlyIncome.trim() === "" || maxDsrPercent.trim() === ""
      ? "Enter your monthly income and maximum DSR limit to see your affordability simulation."
      : null;

  useEffect(() => {
    if (downpaymentError || inputsIncompleteMessage) {
      setResult(null);
      setError(null);
      setIsLoading(false);
      return;
    }
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    fetchDsrSimulator({
      vehicle: vehicleId,
      tenureMonths,
      mileageBand,
      downpayment,
      monthlyIncome,
      maxDsrPercent,
      existingMonthlyCommitments: existingMonthlyCommitments.trim() === "" ? "0" : existingMonthlyCommitments,
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
  }, [
    vehicleId,
    tenureMonths,
    mileageBand,
    downpayment,
    downpaymentError,
    monthlyIncome,
    maxDsrPercent,
    existingMonthlyCommitments,
    inputsIncompleteMessage,
  ]);

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <h2 className="text-h3 font-semibold text-ink">Affordability inputs</h2>
        <p className="mt-1 text-small text-ink-muted">
          See how much of your income each pathway would commit, including any other debt you already carry.
        </p>
        <div className="mt-4 grid grid-cols-1 gap-6 sm:grid-cols-3">
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
          <Input
            label="Existing monthly commitments (RM)"
            type="number"
            min="0"
            step="0.01"
            value={existingMonthlyCommitments}
            onChange={(event) => onExistingMonthlyCommitmentsChange(event.target.value)}
          />
        </div>
      </Card>

      {isLoading && (
        <div className="flex flex-col gap-3">
          <LoadingSkeleton className="h-24 w-full" />
          <LoadingSkeleton className="h-24 w-full" />
          <LoadingSkeleton className="h-24 w-full" />
        </div>
      )}

      {!isLoading && !downpaymentError && inputsIncompleteMessage && (
        <EmptyState title="Complete the inputs above" description={inputsIncompleteMessage} />
      )}

      {!isLoading && !downpaymentError && !inputsIncompleteMessage && error && (
        <EmptyState title="Affordability simulation unavailable" description={error} />
      )}

      {!isLoading && !downpaymentError && !inputsIncompleteMessage && !error && result && (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          {PATHWAY_ORDER.map((pathwayKey) => {
            const pathway = result.pathways[pathwayKey];

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

            return (
              <Card key={pathwayKey} className="flex flex-col gap-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h3 className="flex items-center gap-2 text-[1rem] font-bold text-ink">
                    <span className={cn("h-2.5 w-2.5 shrink-0 rounded-[3px]", PATHWAY_DOT[pathwayKey])} aria-hidden="true" />
                    {PATHWAY_LABELS[pathwayKey]}
                  </h3>
                  <div className="flex flex-wrap items-center gap-2">
                    {pathway.is_ccris_reportable ? (
                      <Badge tone="neutral">CCRIS-reportable</Badge>
                    ) : (
                      <Badge tone="positive">Off-CCRIS</Badge>
                    )}
                    {pathway.exceeds_dsr && <Badge tone="danger">Exceeds your DSR limit</Badge>}
                  </div>
                </div>

                <div>
                  <p className="text-[0.6875rem] font-semibold uppercase tracking-[0.06em] text-ink-muted">Total DSR</p>
                  <p
                    className={cn(
                      "mt-1 text-money-sm font-bold tracking-tight tabular-nums",
                      pathway.exceeds_dsr ? "text-danger-700" : "text-ink",
                    )}
                  >
                    {formatPercent(pathway.dsr_percent)}
                  </p>
                  {/* Run 3 fix batch 5 (F-23): the server's words when 2 dp hide why it is over. */}
                  {pathway.dsr_note && <p className="mt-1 text-caption text-danger-700">{pathway.dsr_note}</p>}
                </div>

                <div>
                  <div
                    className="relative h-2.5 w-full rounded-full bg-surface-subtle"
                    role="progressbar"
                    aria-label={`${PATHWAY_LABELS[pathwayKey]} DSR relative to your limit`}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    // QA audit L16: aria-valuenow must never exceed aria-valuemax - a
                    // DSR over 100% of income is reported as 100 (display only).
                    aria-valuenow={Math.min(Number(pathway.dsr_percent), 100)}
                    aria-valuetext={`${formatPercent(pathway.dsr_percent)} of income; your limit is ${formatPercent(result.max_dsr_percent)}`}
                  >
                    <div className="absolute inset-0 overflow-hidden rounded-full">
                      <div
                        className={cn("h-full rounded-full", pathway.exceeds_dsr ? "bg-danger-600" : "bg-positive-600")}
                        style={{ width: `${pathway.dsr_percent}%` }}
                      />
                    </div>
                    <div
                      className="absolute -top-1 h-[1.125rem] w-0.5 -translate-x-1/2 rounded bg-ink"
                      style={{ left: `${result.max_dsr_percent}%` }}
                      aria-hidden="true"
                    />
                  </div>
                  <p className="mt-1.5 text-caption text-ink-muted">
                    Your limit: <span className="font-semibold text-ink">{formatPercent(result.max_dsr_percent)}</span>
                  </p>
                </div>

                <dl className="grid grid-cols-2 gap-x-4 gap-y-3 border-t border-border pt-3">
                  <div className="min-w-0">
                    <dt className="text-caption font-semibold text-ink-muted">Monthly instalment</dt>
                    <dd className="mt-0.5 text-small font-semibold tabular-nums text-ink">
                      {formatCurrency(pathway.monthly_instalment)}
                    </dd>
                  </div>
                  <div className="min-w-0">
                    <dt className="text-caption font-semibold text-ink-muted">Existing commitments</dt>
                    <dd className="mt-0.5 text-small font-semibold tabular-nums text-ink">
                      {formatCurrency(pathway.existing_monthly_commitments)}
                    </dd>
                  </div>
                </dl>
              </Card>
            );
          })}
          </div>

          <p className="text-caption text-ink-muted">
            Based on your self-declared income and commitments - FlexiDriveMy does not connect to CCRIS or
            any credit bureau.
          </p>
          {/* FX-2 (item 7): what the two badges mean. */}
          <InfoExpander summary="What do CCRIS-reportable and Off-CCRIS mean?" className="text-caption">
            <p>
              CCRIS-reportable: the loan appears in your Bank Negara credit report. Off-CCRIS: the subscription is a
              rental, not a loan.
            </p>
          </InfoExpander>
        </div>
      )}
    </div>
  );
}
