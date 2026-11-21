import type { ReactNode } from "react";
import { Sparkles } from "lucide-react";
import type { ComparisonResult } from "../../types/comparisons";
import type { PathwayKey } from "../../types/scoring";
import { formatCurrency, formatPercent, formatRatioAsPercent } from "../../lib/formatCurrency";
import { NcdNote } from "../common/NcdNote";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { InfoExpander } from "../ui/InfoExpander";
import { StatFigure } from "../ui/StatFigure";
import { cn } from "../ui/cn";

// F005 / UC005's three pathways as cards (redesign UI-3; it was a table) -
// purely presentational, fed a ComparisonResult exactly as the API returned
// it (or a stored UC009 scenario snapshot; the shape is identical either
// way). Shared between ComparisonPage's live "Financing options" tab and
// SavedScenarioPage's read-only reload view, so the two never drift.
//
// One headline per card (the monthly figure); the rate and estimate badges
// stay visible; the server's longer sentences sit in "How is this
// calculated?" and the expanders under the cards - still in the page, one
// click away. Nothing here computes, ranks or picks a pathway: "Recommended"
// appears only when the caller passes the scoring API's own choice.
//
// Usage: <PathwaysTable comparison={comparison} recommendedPathway={scoring?.recommended_pathway} />

// Under the cards, in "Flat vs effective rate", whenever a rate-bearing pathway is present.
export const RATES_NOTE =
  "Rates are shown as flat rates, the way dealers quote them. The effective rate is the reducing-balance equivalent a bank would disclose. Under the Hire-Purchase (Amendment) Act 2026, lenders move to effective-rate disclosure by 31 March 2027, so your final offer may be quoted that way.";
export const ISLAMIC_NOTE = "Indicative: Islamic financing is not priced separately in this app.";
// FX-2 (item 6): the GFV monthly formula in words (the project spec "GFV Leasing") - an explanation, never a calculation.
export const GFV_FORMULA_TEXT =
  "Monthly = (amount financed − balloon) ÷ months + interest on the amount financed (flat rate) ÷ 12";

const PATHWAY_DOT: Record<PathwayKey, string> = {
  hire_purchase: "bg-pathway-hp",
  gfv_leasing: "bg-pathway-gfv",
  subscription: "bg-pathway-sub",
};

interface PathwaysTableProps {
  comparison: ComparisonResult;
  // True when the user's profile says they prefer Islamic financing: the
  // Hire Purchase rate is then labelled "Profit rate" instead of an interest
  // rate. A WORDING change only - no figure differs, and nothing here claims
  // any pathway is Shariah-compliant.
  prefersIslamicFinancing?: boolean;
  // The scoring API's own recommended pathway (UC007), when a recommendation
  // is on the page. Never inferred here; absent/null shows no badge.
  recommendedPathway?: PathwayKey | null;
  // When given (the live compare page), a "Rate your priorities" prompt opens
  // the AI recommendation tab.
  onRatePriorities?: () => void;
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[0.6875rem] font-semibold uppercase tracking-[0.06em] text-ink-muted">{label}</dt>
      <dd className="mt-0.5 text-small font-semibold tabular-nums text-ink">{children}</dd>
    </div>
  );
}

interface PathwayCardProps {
  pathway: PathwayKey;
  name: string;
  isRecommended: boolean;
  monthly: string;
  badges: ReactNode;
  facts: ReactNode;
  extra?: ReactNode;
  basis?: ReactNode;
}

function PathwayCard({ pathway, name, isRecommended, monthly, badges, facts, extra, basis }: PathwayCardProps) {
  return (
    <Card tone={isRecommended ? "highlight" : "default"} className="flex flex-col gap-4" padding="md">
      <article className="flex flex-col gap-4" aria-label={name} data-pathway={pathway}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="flex items-center gap-2 text-[1rem] font-bold text-ink">
            <span className={cn("h-2.5 w-2.5 shrink-0 rounded-[3px]", PATHWAY_DOT[pathway])} aria-hidden="true" />
            {name}
          </h3>
          {isRecommended && <Badge tone="recommended">Recommended</Badge>}
        </div>
        <StatFigure label="Monthly" value={formatCurrency(monthly)} suffix="/ month" size="money" />
        <div className="flex flex-wrap items-center gap-1.5">{badges}</div>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 border-t border-border pt-3">{facts}</dl>
        {extra}
        {basis && <InfoExpander>{basis}</InfoExpander>}
      </article>
    </Card>
  );
}

// FX-3: the lead line for GFV's downpayment limit, from the API's own field
// (never worked out here); nothing is shown when the field is absent or null.
export function gfvMaxDownpaymentLine(value: string | null | undefined): string | null {
  return value ? `Maximum downpayment for GFV at this term: ${formatCurrency(value)}` : null;
}

interface UnavailableCardProps {
  pathway: PathwayKey;
  name: string;
  reason: string | undefined;
  lead?: string | null;
}

function UnavailableCard({ pathway, name, reason, lead }: UnavailableCardProps) {
  return (
    <Card className="flex flex-col gap-3 bg-page-bg shadow-none">
      <article className="flex flex-col gap-3" aria-label={name} data-pathway={pathway}>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="flex items-center gap-2 text-[1rem] font-bold text-ink-muted">
            <span className={cn("h-2.5 w-2.5 shrink-0 rounded-[3px] opacity-50", PATHWAY_DOT[pathway])} aria-hidden="true" />
            {name}
          </h3>
          <Badge tone="danger">Not available</Badge>
        </div>
        {lead && <p className="text-small font-semibold tabular-nums text-ink">{lead}</p>}
        {reason && <p className="text-small text-ink-muted">{reason}</p>}
      </article>
    </Card>
  );
}

export function PathwaysTable({
  comparison,
  prefersIslamicFinancing = false,
  recommendedPathway = null,
  onRatePriorities,
}: PathwaysTableProps) {
  const { hire_purchase: hp, gfv_leasing: gfv, subscription, unavailable } = comparison;
  const gfvLimit = gfvMaxDownpaymentLine(comparison.gfv_max_downpayment);

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {hp ? (
          <PathwayCard
            pathway="hire_purchase"
            name="Hire Purchase"
            isRecommended={recommendedPathway === "hire_purchase"}
            monthly={hp.monthly_instalment}
            badges={
              <>
                <Badge tone="neutral">
                  {prefersIslamicFinancing ? "Profit rate " : ""}
                  {formatPercent(hp.interest_rate_percent)} flat p.a.
                </Badge>
                {hp.effective_rate_percent != null && (
                  <Badge tone="neutral" className="border-dashed font-normal">
                    ≈ {formatPercent(hp.effective_rate_percent)} effective p.a.
                  </Badge>
                )}
              </>
            }
            facts={
              <>
                <Fact label="Upfront cash">{formatCurrency(hp.upfront_cash)}</Fact>
                <Fact label="Total contract outlay">{formatCurrency(hp.total_contract_outlay)}</Fact>
              </>
            }
            // FX-2 (item 7): with the Islamic preference on, the note sits on the card
            // itself, under the "Profit rate" badge (it is also in "Flat vs effective rate").
            extra={prefersIslamicFinancing ? <p className="text-caption text-ink-muted">{ISLAMIC_NOTE}</p> : undefined}
          />
        ) : (
          <UnavailableCard pathway="hire_purchase" name="Hire Purchase" reason={unavailable.hire_purchase} />
        )}

        {gfv ? (
          <PathwayCard
            pathway="gfv_leasing"
            name="GFV Leasing"
            isRecommended={recommendedPathway === "gfv_leasing"}
            monthly={gfv.monthly_instalment}
            badges={
              <>
                <Badge tone="neutral">{formatRatioAsPercent(gfv.residual_value_ratio)} residual</Badge>
                {gfv.effective_rate_percent != null && (
                  <Badge tone="neutral" className="border-dashed font-normal">
                    ≈ {formatPercent(gfv.effective_rate_percent)} effective p.a.
                  </Badge>
                )}
              </>
            }
            facts={
              <>
                <Fact label="Upfront cash">{formatCurrency(gfv.upfront_cash)}</Fact>
                <Fact label="Total contract outlay">{formatCurrency(gfv.total_contract_outlay)}</Fact>
                <Fact label={`Balloon at month ${comparison.tenure_months}`}>{formatCurrency(gfv.balloon_payment)}</Fact>
              </>
            }
            extra={gfvLimit ? <p className="text-caption text-ink-muted">{gfvLimit}</p> : undefined}
            // Where the residual came from (admin override, or the baseline +
            // brand/powertrain estimate) - a server-built string, shown as-is.
            // Absent on older saved snapshots.
            // FX-2 (item 6): the monthly formula in words comes first.
            basis={
              <>
                <p>{GFV_FORMULA_TEXT}</p>
                {gfv.residual_basis && <p className="mt-2">{gfv.residual_basis}</p>}
              </>
            }
          />
        ) : (
          <UnavailableCard pathway="gfv_leasing" name="GFV Leasing" reason={unavailable.gfv_leasing} lead={gfvLimit} />
        )}

        {subscription ? (
          <PathwayCard
            pathway="subscription"
            name="Subscription"
            isRecommended={recommendedPathway === "subscription"}
            monthly={subscription.monthly_instalment}
            badges={
              subscription.fee_source ? (
                <Badge tone={subscription.fee_source === "estimate" ? "estimate" : "neutral"}>
                  {subscription.fee_source === "quote" ? "Provider quote" : "Estimate"}
                </Badge>
              ) : null
            }
            facts={
              <>
                <Fact label="Upfront cash">{formatCurrency(subscription.upfront_cash)}</Fact>
                <Fact label="Total contract outlay">{formatCurrency(subscription.total_contract_outlay)}</Fact>
                {subscription.refundable_deposit != null && (
                  <Fact label="Refundable deposit">{formatCurrency(subscription.refundable_deposit)}</Fact>
                )}
              </>
            }
            extra={
              <>
                {/* Server-built strings, shown as-is; absent on older saved
                    snapshots (which then render exactly as before). */}
                {subscription.mileage_note && <p className="text-small text-ink-muted">{subscription.mileage_note}</p>}
                {subscription.net_cost_after_bundled_benefits !== null && (
                  <div>
                    <p className="text-small text-ink-muted">
                      {/* QA audit H8: monthly_instalment above is the real, gross fee
                          billed - this nets out the insurance/tax/maintenance already
                          bundled into it, purely as additional economic context. */}
                      Effective cost after bundled insurance/road tax/maintenance:{" "}
                      <span className="font-semibold text-ink tabular-nums">
                        {formatCurrency(subscription.net_cost_after_bundled_benefits)}
                      </span>{" "}
                      / month.
                    </p>
                    {/* Run 1 fix batch 3: that offset nets the OWNER's insurance, which
                        takes the buyer's NCD - say when it is the before-NCD figure. */}
                    <NcdNote ncdPercent={comparison.ncd_percent} className="mt-1 text-caption text-ink-muted" />
                  </div>
                )}
              </>
            }
            basis={
              subscription.fee_basis || subscription.refundable_deposit != null ? (
                <div className="flex flex-col gap-2">
                  {subscription.fee_basis && <p>{subscription.fee_basis}</p>}
                  {subscription.refundable_deposit != null && (
                    <p>
                      Refundable deposit {formatCurrency(subscription.refundable_deposit)} is included in upfront
                      cash and returned at the end of the term.
                    </p>
                  )}
                </div>
              ) : undefined
            }
          />
        ) : (
          <UnavailableCard pathway="subscription" name="Subscription" reason={unavailable.subscription} />
        )}
      </div>

      {/* The longer, shared sentences: unchanged, one click away. */}
      <div className="flex flex-col gap-3 rounded-card border border-border bg-surface p-4 sm:flex-row sm:flex-wrap sm:gap-x-8">
        {(hp || gfv) && (
          <InfoExpander summary="Flat vs effective rate">
            <p>{RATES_NOTE}</p>
            {prefersIslamicFinancing && <p className="mt-2">{ISLAMIC_NOTE}</p>}
          </InfoExpander>
        )}
        {gfv && (
          <InfoExpander summary="What happens at the end of GFV">
            <p>
              {/* QA audit H9: total_contract_outlay includes the balloon - wording
                  must agree with the number, not read as an extra on top of it. */}
              Includes the{" "}
              <span className="font-semibold text-ink tabular-nums">{formatCurrency(gfv.balloon_payment)}</span>{" "}
              balloon payment due at end of term, already reflected in the total above.
            </p>
            {/* Run 1 fix batch 4 / Run 2 fix batch 2: what happens at the end, and
                what the residual is - the server's own sentences. */}
            {gfv.end_of_term_note && <p className="mt-2">{gfv.end_of_term_note}</p>}
            {gfv.resale_note && <p className="mt-2">{gfv.resale_note}</p>}
          </InfoExpander>
        )}
        {gfv?.same_total_note && (
          <InfoExpander summary="Why HP and GFV can total the same">
            <p>{gfv.same_total_note}</p>
          </InfoExpander>
        )}
      </div>

      {onRatePriorities && !recommendedPathway && (
        <div className="flex flex-col items-start gap-3 rounded-card border border-primary-200 bg-primary-50 p-4 sm:flex-row sm:items-center sm:justify-between">
          <p className="flex items-center gap-2 text-small font-semibold text-primary-800">
            <Sparkles className="h-4 w-4 shrink-0" aria-hidden="true" />
            Not sure which suits you?
          </p>
          <Button variant="secondary" onClick={onRatePriorities}>
            Rate your priorities
          </Button>
        </div>
      )}
    </div>
  );
}
