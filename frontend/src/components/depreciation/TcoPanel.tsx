import { useEffect, useState } from "react";
import axios from "axios";
import { fetchTcoReport } from "../../api/depreciation";
import { parseApiErrorMessage } from "../../lib/apiErrors";
import type { MileageBand } from "../../types/comparisons";
import type { TcoReport } from "../../types/depreciation";
import { EmptyState } from "../ui/EmptyState";
import { LoadingSkeleton } from "../ui/LoadingSkeleton";
import { TcoReportView } from "./TcoReportView";

// F006 / UC006 "TCO Breakdown & Depreciation" tab. Fetches
// GET /api/depreciation/tco/ on mount and whenever the shared
// tenure/mileage/downpayment inputs change - mounting only while this
// tab is selected (see Tabs.Panel) is what keeps this from being called
// up front alongside F005/F006's endpoints.
//
// Scope note: the backend only returns the negative-equity forecast and
// the 60-month TCO summary. UC006's 3-axis risk radar, month-by-month
// cash flow chart, and contract return checklist aren't modeled by
// apps/depreciation/ yet, so they aren't built here - see the sprint
// summary.

interface TcoPanelProps {
  vehicleId: number;
  tenureMonths: number;
  mileageBand: MileageBand;
  downpayment: string;
  downpaymentError: string | null;
  // Reports the latest successfully-loaded report up to the parent (used
  // by ComparisonPage so F009's "Save this Comparison" can snapshot
  // whatever the user has actually seen) - not used for rendering here.
  onResult?: (report: TcoReport | null) => void;
}

const GENERIC_ERROR = "Could not calculate the TCO breakdown. Please try again.";

export function TcoPanel({
  vehicleId,
  tenureMonths,
  mileageBand,
  downpayment,
  downpaymentError,
  onResult,
}: TcoPanelProps) {
  const [report, setReport] = useState<TcoReport | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (downpaymentError) {
      setReport(null);
      setError(null);
      setIsLoading(false);
      return;
    }
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    fetchTcoReport({ vehicle: vehicleId, tenureMonths, mileageBand, downpayment })
      .then((data) => {
        if (cancelled) return;
        setReport(data);
        onResult?.(data);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setReport(null);
        onResult?.(null);
        if (axios.isAxiosError(err) && err.response?.status === 400) {
          // QA audit M13: a shared parser, not a hardcoded field-name
          // allowlist - picks up the first specific message DRF returns,
          // for whichever field it's actually about.
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
  }, [vehicleId, tenureMonths, mileageBand, downpayment, downpaymentError]);

  if (isLoading) {
    return (
      <div className="flex flex-col gap-3">
        <LoadingSkeleton className="h-80 w-full" />
        <LoadingSkeleton className="h-32 w-full" />
      </div>
    );
  }

  if (error) {
    return <EmptyState title="TCO breakdown unavailable" description={error} />;
  }

  if (!report) return null;

  return <TcoReportView report={report} />;
}
