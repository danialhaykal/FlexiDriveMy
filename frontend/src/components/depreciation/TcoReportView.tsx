import type { TcoReport } from "../../types/depreciation";
import { formatCurrency } from "../../lib/formatCurrency";
import { NcdNote } from "../common/NcdNote";
import { Badge } from "../ui/Badge";
import { Card } from "../ui/Card";
import { InfoExpander } from "../ui/InfoExpander";
import { StatFigure } from "../ui/StatFigure";
import { ContractChecklistCard } from "./ContractChecklistCard";
import { CumulativeCashFlowChart } from "./CumulativeCashFlowChart";
import { NegativeEquityChart } from "./NegativeEquityChart";
import { PathwayTcoTable } from "./PathwayTcoTable";
import { ResaleExplanationCard } from "./ResaleExplanationCard";
import { RiskAlertsCard } from "./RiskAlertsCard";
import { RiskRadarChart } from "./RiskRadarChart";

// F006 / UC006's TCO breakdown - purely presentational, fed a TcoReport
// exactly as the API returned it (or a stored UC009 scenario snapshot;
// the shape is identical either way). Shared between TcoPanel's live fetch
// wrapper and SavedScenarioPage's read-only reload view.
//
// Redesign UI-3 order: what changes the reading of everything below first
// (estimated curve / degraded, risk alerts), then the summary figures, the
// chart, the cost by pathway, why the predicted value is what it is, running
// costs, the radar and cash flow, and the contract checklist. Longer
// explanations are folded into expanders - still in the page. Every figure is
// the API's, shown as sent.
//
// Usage: <TcoReportView report={report} />

interface TcoReportViewProps {
  report: TcoReport;
}

// Run 3 fix batch 5 (F-31): the resale forecast - and so the chart - stops at
// month 60 (the server's HORIZON_MONTHS, apps/depreciation/formulas.py); for a
// longer loan the caption says the chart covers only the first 60 months. Same
// sentence as the PDF (backend apps/exports/comparison_rows.chart_intro).
export const FORECAST_HORIZON_MONTHS = 60;

export function chartIntro(report: Pick<TcoReport, "tenure_months">): string {
  const horizon = FORECAST_HORIZON_MONTHS;
  if (report.tenure_months > horizon) {
    return (
      "Predicted resale value against the outstanding Hire Purchase balance over the first " +
      `${horizon} months of the ${report.tenure_months}-month term; the resale forecast does not go beyond ` +
      `${horizon} months.`
    );
  }
  return `Predicted resale value against the outstanding Hire Purchase balance over the ${report.tenure_months}-month term.`;
}

// FX-3: the running-costs sentence names the yearly maintenance cap the API
// sent (whole ringgit shown without sen); without it (an older snapshot, or
// a rate with no cap) the sentence stays general.
export function maintenanceCapSentence(cap: string | null | undefined): string {
  const amount = cap == null ? Number.NaN : Number(cap);
  if (Number.isNaN(amount)) {
    return "Maintenance is a planning estimate based on the car's price, with a yearly cap, and does not change with the mileage band.";
  }
  const digits = Number.isInteger(amount) ? 0 : 2;
  const text = amount.toLocaleString("en-MY", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return `Maintenance is a planning estimate based on the car's price, capped at RM ${text} a year, and does not change with the mileage band.`;
}

export function TcoReportView({ report }: TcoReportViewProps) {
  // FX-2 (item 7): one horizon wording, from the API's own pathway TCO horizon
  // (Hire Purchase: 60 months). An older snapshot without it keeps the old title.
  const tcoHorizon = report.pathway_tco?.hire_purchase?.horizon_months;
  return (
    // Redesign UI-6b: a little tighter between the tab's cards (was gap-6).
    <div className="flex flex-col gap-4 sm:gap-5">
      {/* Run 2 fix batch 3 (A14, X1): a car the model doesn't cover (electric, no
          engine size, body type not mapped) uses the estimated curve by design -
          a neutral "Estimated curve", not a fault. The amber "Degraded" stays for
          a model that isn't available, and for a snapshot saved before
          forecast_source existed. The reason is the server's own sentence. */}
      {report.model_degraded && report.forecast_source === "estimated_curve_unsupported" && (
        <div className="flex items-start gap-3 rounded-card border border-border bg-surface p-3">
          <Badge tone="neutral">Estimated curve</Badge>
          <p className="text-small text-ink-muted">{report.degraded_reason}</p>
        </div>
      )}
      {report.model_degraded && report.forecast_source !== "estimated_curve_unsupported" && (
        <div className="flex items-start gap-3 rounded-card border border-warning-200 bg-warning-50 p-3">
          <Badge tone="warning">Degraded</Badge>
          <p className="text-small text-warning-700">{report.degraded_reason}</p>
        </div>
      )}

      <RiskAlertsCard alerts={report.risk_alerts} />

      <Card>
        <h2 className="text-h3 font-semibold text-ink">
          {tcoHorizon ? `Total cost over ${tcoHorizon} months` : "60-month total cost of ownership"}
        </h2>
        {tcoHorizon && report.tenure_months !== tcoHorizon && (
          <p className="mt-1 text-small text-ink-muted">
            The loan runs {report.tenure_months} months; total cost is measured over {tcoHorizon} months so every
            option compares on the same period.
          </p>
        )}
        <div className="mt-4 grid grid-cols-1 gap-5 sm:grid-cols-3">
          <StatFigure label="Monthly HP instalment" value={formatCurrency(report.hp_monthly)} size="money-sm" />
          <StatFigure label="Total cost, Hire Purchase (gross)" value={formatCurrency(report.tco_gross)} size="money-sm" />
          <StatFigure label="Total cost after resale value (net)" value={formatCurrency(report.tco_net)} size="money-sm" />
        </div>
        {/* The net figure credits net equity at month 60: predicted resale
            value minus the estimated amount to settle the loan then (the
            reducing-balance settlement_balance, zero once a loan of 60 months
            or less is repaid). */}
        <InfoExpander summary="What does net mean?" className="mt-4">
          <p>
            Net TCO credits your estimated equity at month 60 (predicted resale value minus the
            estimated amount to settle the loan, reducing-balance method) - your lender's settlement
            letter is the final figure.
          </p>
        </InfoExpander>
      </Card>

      <Card>
        <h2 className="text-h3 font-semibold text-ink">Remaining loan vs. predicted car value</h2>
        <p className="mt-1 text-small text-ink-muted">{chartIntro(report)}</p>
        {/* Run 3 fix batch 6: the server's note when the mileage cap changed the
            forecast; null otherwise, absent from older snapshots. Always visible. */}
        {report.forecast_cap_note && <p className="mt-1 text-small font-medium text-ink">{report.forecast_cap_note}</p>}
        {/* Run 2 fix batch 2 (C6, E5): what the predicted curve is and its typical
            error - the server's sentence; null on the estimated fallback curve and
            absent from an older saved snapshot. */}
        {report.resale_forecast_note && (
          <InfoExpander summary="About this forecast" className="mt-2">
            <p>{report.resale_forecast_note}</p>
          </InfoExpander>
        )}
        <div className="mt-4">
          <NegativeEquityChart
            monthlyForecast={report.monthly_forecast}
            crossoverMonth={report.negative_equity_crossover_month}
            shortfallAmount={report.negative_equity_shortfall_amount}
          />
        </div>
      </Card>

      {/* Run 1 fix batch 4: every pathway's TCO. Absent from a report saved
          before it existed - that snapshot shows the HP figures above only. */}
      {report.pathway_tco && (
        <PathwayTcoTable pathwayTco={report.pathway_tco} resaleViewsNote={report.resale_views_note} />
      )}

      {report.resale_value_explanation && <ResaleExplanationCard explanation={report.resale_value_explanation} />}

      <Card>
        <h2 className="text-h3 font-semibold text-ink">Yearly running costs</h2>
        <p className="mt-1 text-small text-ink-muted">Road tax, comprehensive insurance and maintenance.</p>
        <dl className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
          {[
            { label: "Road tax", value: report.road_tax_annual },
            { label: "Insurance", value: report.insurance_annual },
            { label: "Maintenance", value: report.maintenance_annual },
          ].map(({ label, value }) => (
            <div key={label} className="rounded-control border border-border bg-page-bg px-4 py-3">
              <dt className="text-caption font-semibold text-ink-muted">{label}</dt>
              <dd className="mt-0.5 text-body font-semibold tabular-nums text-ink">{formatCurrency(value)} / yr</dd>
            </div>
          ))}
        </dl>
        {/* Run 1 fix batch 3: the road-tax line names the registration class and
            the insurance line any No-Claim Discount (both from the API). */}
        <InfoExpander summary="How are these estimated?" className="mt-4">
          {report.operating_cost_basis && (
            <ul className="flex flex-col gap-1">
              <li>{report.operating_cost_basis.road_tax}</li>
              <li>{report.operating_cost_basis.insurance}</li>
              <li>{report.operating_cost_basis.maintenance}</li>
            </ul>
          )}
          <p className={report.operating_cost_basis ? "mt-2" : undefined}>
            Estimates for Peninsular Malaysia, private car; insurance and maintenance are planning
            assumptions, not quotes.
          </p>
          {/* FX-3: the cap's amount comes from the API's operating_cost_policy (older snapshots lack it). */}
          <p className="mt-2">{maintenanceCapSentence(report.operating_cost_policy?.maintenance_cap_annual)}</p>
        </InfoExpander>
        <NcdNote ncdPercent={report.ncd_percent} className="mt-2 text-caption text-ink-muted" />
        {report.ncd_percent === undefined && (
          // A saved report from before NCD existed: its insurance had none.
          <p className="mt-2 text-caption text-ink-muted">Insurance shown before No-Claim Discount.</p>
        )}
      </Card>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Card>
          <h2 className="text-h3 font-semibold text-ink">3-axis risk comparison</h2>
          <InfoExpander summary="What does this chart show?" className="mt-1">
            <p>
              Upfront cash preservation, maintenance cost protection, and ownership equity, scored per
              pathway (0-1, higher is better) - the same unweighted scores the recommendation's suitability
              scoring uses.
            </p>
          </InfoExpander>
          <div className="mt-4">
            <RiskRadarChart radar={report.risk_radar} unavailable={report.radar_unavailable} />
          </div>
        </Card>

        <Card>
          <h2 className="text-h3 font-semibold text-ink">Cumulative cash flow</h2>
          <InfoExpander summary="What does this chart show?" className="mt-1">
            <p>Running total of cash paid out under the Hire Purchase pathway, month by month.</p>
          </InfoExpander>
          <div className="mt-4">
            <CumulativeCashFlowChart cumulativeCashFlow={report.cumulative_cash_flow} />
          </div>
        </Card>
      </div>

      <ContractChecklistCard checklist={report.contract_checklist} />
    </div>
  );
}
