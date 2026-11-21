import type { ReactNode } from "react";
import { CircleGauge, HandCoins, Undo2, Wrench } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { formatCurrency } from "../../lib/formatCurrency";
import type { ContractChecklist } from "../../types/depreciation";
import { Card } from "../ui/Card";
import { EmptyState } from "../ui/EmptyState";
import { InfoExpander } from "../ui/InfoExpander";

// UC006 step 8's contract return checklist - wear-and-tear tolerances,
// excess mileage charges, and the cost of an early exit, sourced from
// apps.policy.models.ContractPenaltyRule: the brand's own rule, else the single
// default rule, so a new brand still has terms. Every figure is computed
// server-side - this card only displays what the API sent.
//
// Two early exits, never mixed up (run 1, B7):
//   - settling a Hire Purchase loan early: the reducing-balance amount to
//     settle, no penalty (Hire-Purchase (Amendment) Act 2026);
//   - returning a subscription car early: N months of the subscription fee,
//     or the fees left, whichever is lower.
// A saved scenario from before that has no `early_settlement` and keeps its
// old single "Early termination" row, exactly as it was saved.

interface ContractChecklistCardProps {
  // Live-walkthrough finding: `| undefined` for real, distinct from the
  // explicit `null` the live API sends for "no rule configured" - a
  // scenario saved before Batch 6C added this field has no
  // `contract_checklist` key at all in its stored payload
  // (SavedScenarioPage.tsx renders whatever was actually saved,
  // unchanged), so `checklist` is `undefined` there, never `null`.
  checklist: ContractChecklist | null | undefined;
}

// "3.00" -> "3", "2.50" -> "2.5" (display only; the value is the API's).
function trimMonths(months: string): string {
  return months.includes(".") ? months.replace(/0+$/, "").replace(/\.$/, "") : months;
}

function monthsWord(months: string): string {
  return trimMonths(months) === "1" ? "month" : "months";
}

function ruleSourceNote(checklist: ContractChecklist): string | null {
  const isCurrent = checklist.early_settlement != null;
  if (checklist.rule_source === "default") {
    return "Terms from the default contract rule - planning estimates; typical terms vary by provider.";
  }
  if (checklist.rule_source === "brand") {
    if (checklist.early_termination_months_source !== "default") return "Terms from this brand's own contract rule.";
    return isCurrent
      ? "Terms from this brand's own contract rule (subscription early-return months from the default rule)."
      : "Terms from this brand's own contract rule (early-termination months from the default rule).";
  }
  return null; // a saved snapshot from before audit batch 4
}

// A saved snapshot from before run 1: its single row, exactly as it was saved.
function LegacyEarlyTermination({ checklist }: { checklist: ContractChecklist }) {
  const { early_termination_months: months, early_termination_amount: amount, early_termination_fee: fee } = checklist;
  if (months != null) {
    return (
      <>
        Up to {trimMonths(months)} {monthsWord(months)} of instalments
        {amount != null && <> (about {formatCurrency(amount)})</>}
      </>
    );
  }
  // A frozen pre-batch-4 snapshot: its stored ringgit amount, shown as saved.
  if (fee != null) return <>{formatCurrency(fee)}</>;
  return <>Not configured</>;
}

function HirePurchaseEarlySettlement({ checklist }: { checklist: ContractChecklist }) {
  const settlement = checklist.early_settlement!;
  return (
    <>
      No penalty under the reducing-balance method.
      {settlement.after_12_months != null && (
        <> Estimated amount to settle after 12 months: {formatCurrency(settlement.after_12_months)};</>
      )}{" "}
      {settlement.after_12_months != null ? "at" : "Estimated amount to settle at"} month{" "}
      {settlement.half_term_month}: {formatCurrency(settlement.at_half_term)}.
    </>
  );
}

function SubscriptionEarlyReturn({ checklist }: { checklist: ContractChecklist }) {
  const months = checklist.subscription_early_return_months ?? checklist.early_termination_months ?? null;
  const fee = checklist.subscription_early_return_fee ?? null;
  if (months == null) return <>Not configured</>;
  if (fee == null) {
    return (
      <>
        Up to {trimMonths(months)} {monthsWord(months)} of the subscription fee.
      </>
    );
  }
  return (
    <>
      Up to {trimMonths(months)} {monthsWord(months)} of the subscription fee (about {formatCurrency(fee)}), or
      the fees left, whichever is lower.
    </>
  );
}

// One compact checklist row: an icon, the label (dt) and the value (dd).
function ChecklistRow({ icon: Icon, label, children }: { icon: LucideIcon; label: string; children: ReactNode }) {
  return (
    <div className="flex items-start gap-3 py-3">
      <span className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-control bg-page-bg">
        <Icon className="h-4 w-4 text-ink-muted" aria-hidden="true" />
      </span>
      <div className="min-w-0">
        <dt className="text-caption font-semibold text-ink-muted">{label}</dt>
        <dd className="mt-0.5 text-small text-ink">{children}</dd>
      </div>
    </div>
  );
}

// Redesign UI-3: a compact list (icon, label, value); the long brand text (the
// wear-and-tear tolerance), the card's explanation and where the terms come
// from are folded into expanders - still in the page. All values unchanged.
export function ContractChecklistCard({ checklist }: ContractChecklistCardProps) {
  const sourceNote = checklist == null ? null : ruleSourceNote(checklist);
  const isCurrent = checklist != null && checklist.early_settlement != null;
  return (
    <Card>
      <h2 className="text-h3 font-semibold text-ink">Contract return checklist</h2>
      <InfoExpander summary="What this checklist covers" className="mt-1">
        <p>
          Wear-and-tear tolerances, excess mileage charges, and what leaving early costs for this brand.
          Wear and tear is a checklist item only, not a cost in the totals: normal wear is already
          priced into the car&apos;s resale value, and only excess damage at return is billed.
        </p>
      </InfoExpander>

      {checklist == null ? (
        <EmptyState
          className="mt-4 border-0 p-6"
          title="Contract terms not yet configured for this brand"
        />
      ) : (
        <>
          <dl className="mt-2 divide-y divide-border">
            <ChecklistRow icon={CircleGauge} label="Excess mileage charge">
              <span className="font-semibold tabular-nums">{formatCurrency(checklist.excess_mileage_charge_per_km)} / km (estimate)</span>
            </ChecklistRow>
            {isCurrent ? (
              <>
                <ChecklistRow icon={HandCoins} label="Settling a Hire Purchase loan early">
                  <HirePurchaseEarlySettlement checklist={checklist} />
                </ChecklistRow>
                <ChecklistRow icon={Undo2} label="Returning a subscription car early">
                  <SubscriptionEarlyReturn checklist={checklist} />
                </ChecklistRow>
              </>
            ) : (
              <ChecklistRow icon={Undo2} label="Early termination">
                <span className="font-semibold tabular-nums">
                  <LegacyEarlyTermination checklist={checklist} />
                </span>
              </ChecklistRow>
            )}
            <ChecklistRow icon={Wrench} label="Wear & tear tolerance">
              <InfoExpander summary="Read the brand's terms">
                <p className="text-ink">{checklist.wear_tear_tolerance_description}</p>
              </InfoExpander>
            </ChecklistRow>
          </dl>
          {sourceNote && (
            <InfoExpander summary="Where these terms come from" className="mt-2">
              <p>{sourceNote}</p>
            </InfoExpander>
          )}
        </>
      )}
    </Card>
  );
}
