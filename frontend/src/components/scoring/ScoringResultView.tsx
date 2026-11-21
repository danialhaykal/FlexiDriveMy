import { useId } from "react";
import { Trophy } from "lucide-react";
import type { PathwayKey, ScoringResult } from "../../types/scoring";
import { PATHWAY_LABELS } from "../../types/scoring";
import { formatCurrency, formatPercent } from "../../lib/formatCurrency";
import { Badge } from "../ui/Badge";
import { Card } from "../ui/Card";
import { cn } from "../ui/cn";

// F007 / UC007's ranked recommendation - purely presentational, fed a
// ScoringResult exactly as the API returned it (or a stored UC009
// scenario snapshot; the shape is identical either way). Shared between
// RecommendationPanel's live fetch wrapper and SavedScenarioPage's
// read-only reload view.
//
// Redesign UI-3: the answer first - a highlighted "Best match" card for the
// API's recommended_pathway, with its score, the API's rationale, monthly
// and DSR - then the API's ranking as rows. Order, scores, ties and 0%
// scores are exactly the API's; the score bar's width IS the API's score
// percentage (display only). Nothing is ranked or picked here.
//
// Usage: <ScoringResultView result={result} />

interface ScoringResultViewProps {
  result: ScoringResult;
}

const PATHWAY_DOT: Record<PathwayKey, string> = {
  hire_purchase: "bg-pathway-hp",
  gfv_leasing: "bg-pathway-gfv",
  subscription: "bg-pathway-sub",
};

function Dot({ pathway }: { pathway: PathwayKey }) {
  return <span className={cn("h-2.5 w-2.5 shrink-0 rounded-[3px]", PATHWAY_DOT[pathway])} aria-hidden="true" />;
}

function DsrState({ exceeds }: { exceeds: boolean }) {
  return exceeds ? <Badge tone="danger">Exceeds DSR</Badge> : <Badge tone="positive">Within limit</Badge>;
}

export function ScoringResultView({ result }: ScoringResultViewProps) {
  const rankingHeadingId = useId();
  const unavailableKeys = Object.keys(result.unavailable ?? {}) as PathwayKey[];
  const bestKey = result.recommended_pathway;
  const best = bestKey ? result.pathways[bestKey] : undefined;

  return (
    <div className="flex flex-col gap-6">
      {bestKey && best ? (
        <Card tone="highlight">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex items-center gap-3">
              <span className="grid h-10 w-10 shrink-0 place-items-center rounded-control bg-primary-50">
                <Trophy className="h-5 w-5 text-primary-700" aria-hidden="true" />
              </span>
              <div>
                <p className="text-caption font-semibold uppercase tracking-[0.06em] text-ink-muted">Best match</p>
                <h3 className="flex items-center gap-2 text-h3 font-bold text-ink">
                  <Dot pathway={bestKey} />
                  {PATHWAY_LABELS[bestKey]}
                </h3>
              </div>
            </div>
            <div className="flex flex-col items-end gap-1">
              <Badge tone="recommended">Recommended</Badge>
              <p className="text-small font-semibold tabular-nums text-primary-700">
                {formatPercent(best.suitability_score)} suitability
              </p>
            </div>
          </div>
          <p className="mt-3 text-small text-ink">{result.rationale}</p>
          <dl className="mt-4 flex flex-wrap gap-x-8 gap-y-3 border-t border-border pt-3">
            <div>
              <dt className="text-[0.6875rem] font-semibold uppercase tracking-[0.06em] text-ink-muted">Monthly</dt>
              <dd className="mt-0.5 text-body font-semibold tabular-nums text-ink">
                {formatCurrency(best.monthly_instalment)} / month
              </dd>
            </div>
            <div>
              <dt className="text-[0.6875rem] font-semibold uppercase tracking-[0.06em] text-ink-muted">DSR</dt>
              <dd className="mt-0.5 flex items-center gap-2 text-body font-semibold tabular-nums text-ink">
                {formatPercent(best.dsr_percent)} of income
                <DsrState exceeds={best.exceeds_dsr} />
              </dd>
            </div>
          </dl>
        </Card>
      ) : (
        // No pathway recommended (e.g. every one exceeds the DSR limit): the
        // API's own sentence explains why.
        <div className="rounded-card border border-border bg-surface p-4">
          <p className="text-small text-ink">{result.rationale}</p>
        </div>
      )}

      <Card padding="none">
        <h3 id={rankingHeadingId} className="px-4 pt-4 text-small font-semibold text-ink-muted sm:px-6">
          Full ranking
        </h3>
        <ol aria-labelledby={rankingHeadingId} className="divide-y divide-border">
          {result.ranking.map((key, index) => {
            const pathway = result.pathways[key];
            if (!pathway) return null;
            return (
              <li
                key={key}
                className="grid grid-cols-1 gap-3 px-4 py-4 sm:px-6 md:grid-cols-[minmax(0,1.3fr)_minmax(0,1.6fr)_minmax(0,1fr)_minmax(0,1.3fr)] md:items-center"
              >
                <div className="flex items-center gap-2">
                  <span className="w-6 text-caption font-semibold text-ink-muted">#{index + 1}</span>
                  <Dot pathway={key} />
                  <span className="text-small font-semibold text-ink" data-ranking-name>
                    {PATHWAY_LABELS[key]}
                  </span>
                </div>
                <div className="flex items-center gap-3">
                  <div
                    className="h-2 flex-1 overflow-hidden rounded-full bg-surface-subtle"
                    role="img"
                    aria-label={`${PATHWAY_LABELS[key]} suitability ${formatPercent(pathway.suitability_score)}`}
                  >
                    {/* The width is the API's score percentage, as sent (display only). */}
                    <div className={cn("h-full rounded-full", PATHWAY_DOT[key])} style={{ width: `${pathway.suitability_score}%` }} />
                  </div>
                  <span className="w-16 text-right text-small font-semibold tabular-nums text-ink">
                    {formatPercent(pathway.suitability_score)}
                  </span>
                </div>
                <div className="text-small tabular-nums text-ink md:text-right">
                  <span className="text-caption text-ink-muted md:hidden">Monthly </span>
                  {formatCurrency(pathway.monthly_instalment)}
                </div>
                <div className="flex flex-col gap-1 md:items-end">
                  <div className="flex items-center gap-2">
                    <span className="text-caption text-ink-muted">DSR</span>
                    <span className="text-small font-semibold tabular-nums text-ink">{formatPercent(pathway.dsr_percent)}</span>
                    <DsrState exceeds={pathway.exceeds_dsr} />
                  </div>
                  {/* Run 3 fix batch 5 (F-23): the server's words when 2 dp hide why it is over. */}
                  {pathway.dsr_note && <p className="text-caption text-danger-700">{pathway.dsr_note}</p>}
                </div>
              </li>
            );
          })}
        </ol>
      </Card>

      {unavailableKeys.map((key) => (
        <Card key={key} className="bg-page-bg shadow-none">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="flex items-center gap-2 text-[1rem] font-bold text-ink-muted">
              <Dot pathway={key} />
              {PATHWAY_LABELS[key]}
            </h3>
            <Badge tone="danger">Not available</Badge>
          </div>
          <p className="mt-2 text-small text-ink-muted">{result.unavailable[key]}</p>
        </Card>
      ))}
    </div>
  );
}
