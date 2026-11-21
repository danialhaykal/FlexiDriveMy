import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { fetchComparison } from "../../api/comparisons";
import { useMileageBandOptions } from "../../hooks/useMileageBandOptions";
import { QUICK_LOOK_TENURE_MONTHS } from "../../lib/defaults";
import { formatCurrency, formatRatioAsPercent } from "../../lib/formatCurrency";
import type { ComparisonResult, MileageBand } from "../../types/comparisons";
import type { Vehicle } from "../../types/catalog";
import { Badge } from "../ui/Badge";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { StatFigure } from "../ui/StatFigure";
import { cn } from "../ui/cn";

// "Monthly at a glance" on the vehicle page: the three pathways' monthly
// figures from the EXISTING comparison endpoint - 36 months, the standard
// band and the API's own minimum downpayment - shown exactly as returned.
// Nothing is computed here; "See the full comparison" opens the compare page
// on the same three inputs, so its figures are the same ones.

const QUICK_LOOK_BAND: MileageBand = "standard";

export function quickLookCompareUrl(vehicle: Pick<Vehicle, "id" | "min_downpayment">): string {
  const params = new URLSearchParams({
    tenure: String(QUICK_LOOK_TENURE_MONTHS),
    mileage: QUICK_LOOK_BAND,
    downpayment: vehicle.min_downpayment,
  });
  return `/catalog/${vehicle.id}/compare?${params.toString()}`;
}

interface PathwayCardProps {
  name: string;
  dotClass: string;
  monthly: string | undefined;
  unavailableReason: string | undefined;
  badge?: ReactNode;
}

function PathwayCard({ name, dotClass, monthly, unavailableReason, badge }: PathwayCardProps) {
  return (
    <Card className="flex flex-col gap-3" padding="md">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-2 font-display text-[0.9375rem] font-bold text-ink">
          <span className={cn("h-2.5 w-2.5 shrink-0 rounded-[3px]", dotClass)} aria-hidden="true" />
          {name}
        </span>
        {monthly !== undefined && badge}
      </div>
      {monthly !== undefined ? (
        <StatFigure label="Monthly" value={formatCurrency(monthly)} suffix="/ month" size="money-sm" />
      ) : (
        <div className="flex flex-col items-start gap-1.5">
          <Badge tone="danger">Not available</Badge>
          {unavailableReason && <p className="text-small text-ink-muted">{unavailableReason}</p>}
        </div>
      )}
    </Card>
  );
}

export function QuickLook({ vehicle }: { vehicle: Pick<Vehicle, "id" | "min_downpayment"> }) {
  const bands = useMileageBandOptions();
  const bandLabel = bands.find((band) => band.value === QUICK_LOOK_BAND)?.label ?? "Standard";
  const [comparison, setComparison] = useState<ComparisonResult | null>(null);
  const [error, setError] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setIsLoading(true);
    setError(false);
    fetchComparison({
      vehicle: vehicle.id,
      tenureMonths: QUICK_LOOK_TENURE_MONTHS,
      mileageBand: QUICK_LOOK_BAND,
      downpayment: vehicle.min_downpayment,
    })
      .then((data) => {
        if (!cancelled) setComparison(data);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [vehicle.id, vehicle.min_downpayment, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  return (
    <section aria-labelledby="quick-look-heading" className="mt-10">
      <h2 id="quick-look-heading" className="text-h3 font-bold text-ink">
        Monthly at a glance
      </h2>
      <p className="mt-1 text-small text-ink-muted">
        {QUICK_LOOK_TENURE_MONTHS} months · {bandLabel} · minimum downpayment {formatCurrency(vehicle.min_downpayment)}
      </p>

      {isLoading && (
        <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3" aria-hidden="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-[7.5rem] animate-pulse rounded-card border border-border bg-surface-subtle" />
          ))}
        </div>
      )}

      {!isLoading && error && (
        <div role="alert" className="mt-4 flex flex-wrap items-center gap-3 rounded-card border border-danger-200 bg-danger-50 p-4">
          <p className="text-small text-danger-700">The monthly figures could not be loaded just now.</p>
          <Button variant="secondary" onClick={retry}>
            Try again
          </Button>
        </div>
      )}

      {!isLoading && !error && comparison && (
        <>
          <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
            <PathwayCard
              name="Hire Purchase"
              dotClass="bg-pathway-hp"
              monthly={comparison.hire_purchase?.monthly_instalment}
              unavailableReason={comparison.unavailable.hire_purchase}
            />
            <PathwayCard
              name="GFV Leasing"
              dotClass="bg-pathway-gfv"
              monthly={comparison.gfv_leasing?.monthly_instalment}
              unavailableReason={comparison.unavailable.gfv_leasing}
              badge={
                comparison.gfv_leasing && (
                  <Badge tone="neutral">{formatRatioAsPercent(comparison.gfv_leasing.residual_value_ratio)} residual</Badge>
                )
              }
            />
            <PathwayCard
              name="Subscription"
              dotClass="bg-pathway-sub"
              monthly={comparison.subscription?.monthly_instalment}
              unavailableReason={comparison.unavailable.subscription}
              badge={
                comparison.subscription?.fee_source && (
                  <Badge tone={comparison.subscription.fee_source === "estimate" ? "estimate" : "neutral"}>
                    {comparison.subscription.fee_source === "quote" ? "Provider quote" : "Estimate"}
                  </Badge>
                )
              }
            />
          </div>
          <Link
            to={quickLookCompareUrl(vehicle)}
            className="mt-4 inline-flex items-center gap-1 rounded-control text-small font-semibold text-primary-700 hover:text-primary-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2"
          >
            See the full comparison
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Link>
        </>
      )}
    </section>
  );
}
