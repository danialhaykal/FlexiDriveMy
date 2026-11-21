import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { Link, useParams } from "react-router-dom";
import { CalendarDays, CarFront, ChevronLeft, Cog, ExternalLink, Fuel, Gauge, Zap } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { fetchVehicleDetail } from "../api/catalog";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import type { Vehicle } from "../types/catalog";
import { formatCurrency } from "../lib/formatCurrency";
import { SERVER_UNREACHABLE_MESSAGE, isNotFoundError } from "../lib/apiErrors";
import { bodySegmentLabel, formatPowerKw, powertrainLabel } from "../lib/vehicleLabels";
import { wikimediaFilePageUrl } from "../lib/wikimediaCredit";
import { VehiclePhotoPlaceholder } from "../components/catalog/VehiclePhotoPlaceholder";
import { QuickLook, quickLookCompareUrl } from "../components/catalog/QuickLook";
import { StatFigure } from "../components/ui/StatFigure";
import { Button } from "../components/ui/Button";

// One spec tile: an icon and a label (dt) over the value (dd). Only rows that
// have data are rendered - a missing value is left out, never guessed.
function SpecTile({ icon: Icon, label, children }: { icon: LucideIcon; label: string; children: ReactNode }) {
  return (
    <div className="rounded-control border border-border bg-page-bg px-3 py-2.5">
      <dt className="flex items-center gap-1.5 text-caption font-semibold text-ink-muted">
        <Icon className="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
        {label}
      </dt>
      <dd className="mt-0.5 text-small font-semibold text-ink">{children}</dd>
    </div>
  );
}

export function VehicleDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [vehicle, setVehicle] = useState<Vehicle | null>(null);
  useDocumentTitle(vehicle ? `${vehicle.brand_name} ${vehicle.name} ${vehicle.trim}` : "Vehicle Detail");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // FX-2 (item 1): only a 404 is "not found"; anything else can be retried.
  const [canRetry, setCanRetry] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    setIsLoading(true);
    setError(null);
    fetchVehicleDetail(id)
      .then((data) => {
        if (!cancelled) setVehicle(data);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const notFound = isNotFoundError(err);
        setError(notFound ? "This vehicle could not be found." : SERVER_UNREACHABLE_MESSAGE);
        setCanRetry(!notFound);
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [id, reloadKey]);

  if (isLoading) {
    return (
      <p className="mt-10 text-center text-small text-ink-muted" role="status">
        Loading…
      </p>
    );
  }

  if (error || !vehicle) {
    return (
      <div className="mx-auto max-w-6xl px-4 py-10 text-center">
        <p role="alert" className="text-small text-danger-700">
          {error ?? "Vehicle not found."}
        </p>
        {canRetry && (
          <div className="mt-3">
            <Button onClick={() => setReloadKey((key) => key + 1)}>Try again</Button>
          </div>
        )}
        <Link to="/catalog" className="mt-3 inline-block text-small font-semibold text-primary-700 underline">
          Back to catalog
        </Link>
      </div>
    );
  }

  const segment = bodySegmentLabel(vehicle.body_segment);
  const creditUrl = wikimediaFilePageUrl(vehicle.thumbnail_url);

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:py-10">
      <Link
        to="/catalog"
        className="inline-flex items-center gap-1 rounded-control text-small font-medium text-ink-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500"
      >
        <ChevronLeft className="h-4 w-4" aria-hidden="true" />
        Back to catalog
      </Link>

      <div className="mt-4 grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,55fr)_minmax(0,45fr)] lg:gap-8">
        <div>
          <div className="aspect-[16/10] w-full overflow-hidden rounded-card border border-border bg-surface-subtle shadow-card">
            {vehicle.thumbnail_url ? (
              <img
                src={vehicle.thumbnail_url}
                alt={`${vehicle.brand_name} ${vehicle.name}`}
                className="h-full w-full object-cover"
              />
            ) : (
              <VehiclePhotoPlaceholder brandName={vehicle.brand_name} modelName={vehicle.name} segmentLabel={segment} size="lg" />
            )}
          </div>
          {/* Credit for a Wikimedia Commons photo: its file page names the
              author and the licence. Worked out from the URL; any other host
              shows nothing. */}
          {creditUrl && (
            <p className="mt-2 text-caption text-ink-muted">
              Photo:{" "}
              <a
                href={creditUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-0.5 font-medium text-primary-700 underline hover:text-primary-800"
              >
                Wikimedia Commons
                <ExternalLink className="h-3 w-3" aria-hidden="true" />
              </a>
            </p>
          )}
        </div>

        <div className="flex flex-col">
          <p className="text-small text-ink-muted">
            {vehicle.brand_name}
            {vehicle.model_year ? ` · ${vehicle.model_year}` : ""}
          </p>
          <h1 className="mt-1 text-[1.625rem] font-bold leading-tight text-ink sm:text-[1.875rem]">
            {vehicle.name} {vehicle.trim}
          </h1>

          <div className="mt-5 flex flex-wrap items-end gap-x-8 gap-y-4">
            <StatFigure label="Price" value={formatCurrency(vehicle.msrp)} size="money" />
            {/* The API's own minimum (min_downpayment); the rule behind it is
                not restated here. */}
            <StatFigure label="Minimum downpayment" value={formatCurrency(vehicle.min_downpayment)} />
          </div>

          {/* FX-1 (X4): the same inputs as "Monthly at a glance" (36 months, Standard, the API's minimum
              downpayment), so the comparison opens on the figures the buyer just saw. */}
          <Link
            to={quickLookCompareUrl(vehicle)}
            className="mt-6 inline-flex items-center justify-center gap-2 self-start rounded-control bg-primary-600 px-5 py-2.5 text-small font-semibold text-white transition-colors hover:bg-primary-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2"
          >
            Compare Financing Options
          </Link>

          <dl className="mt-6 grid grid-cols-2 gap-2.5">
            {/* engine_capacity_kw is POWER OUTPUT (legacy field name); the
                displacement is the separate cc row. */}
            {formatPowerKw(vehicle.engine_capacity_kw) && (
              <SpecTile icon={Gauge} label="Power output">
                {formatPowerKw(vehicle.engine_capacity_kw)}
              </SpecTile>
            )}
            {/* Only rows that have data: a legacy row with no powertrain/cc yet
                shows neither, rather than a guess. */}
            {vehicle.powertrain === "bev" ? (
              <SpecTile icon={Zap} label="Engine">
                Electric motor
              </SpecTile>
            ) : (
              vehicle.engine_capacity_cc !== null && (
                <SpecTile icon={Cog} label="Engine">
                  {vehicle.engine_capacity_cc.toLocaleString("en-MY")} cc
                </SpecTile>
              )
            )}
            {vehicle.powertrain && (
              <SpecTile icon={Fuel} label="Powertrain">
                {powertrainLabel(vehicle.powertrain)}
              </SpecTile>
            )}
            {vehicle.model_year && (
              <SpecTile icon={CalendarDays} label="Model year">
                {vehicle.model_year}
              </SpecTile>
            )}
            {segment && (
              <SpecTile icon={CarFront} label="Body segment">
                {segment}
              </SpecTile>
            )}
          </dl>
        </div>
      </div>

      {/* Its own loading and "Try again" state: a failure here never hides the page above. */}
      <QuickLook vehicle={vehicle} />
    </div>
  );
}
