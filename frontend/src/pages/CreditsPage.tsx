import { useEffect, useState } from "react";
import { fetchEntireCatalog } from "../api/catalog";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { wikimediaFilePageUrl } from "../lib/wikimediaCredit";
import { EMPTY_CATALOG_FILTERS } from "../types/catalog";
import type { Vehicle } from "../types/catalog";
import { Button } from "../components/ui/Button";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/EmptyState";
import { LoadingSkeleton } from "../components/ui/LoadingSkeleton";
import { PageHeader } from "../components/ui/PageHeader";

// FX-2 (item 8): photo credits. Every active car whose photo is a Wikimedia
// Commons file, with the link to its file page (author and licence are there),
// worked out from the catalog data by the same helper as the vehicle page -
// nothing is keyed per car.
export function CreditsPage() {
  useDocumentTitle("Photo credits");
  const [vehicles, setVehicles] = useState<Vehicle[] | null>(null);
  const [error, setError] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setVehicles(null);
    setError(false);
    fetchEntireCatalog(EMPTY_CATALOG_FILTERS)
      .then((data) => {
        if (!cancelled) setVehicles(data);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  const credited = (vehicles ?? [])
    .map((vehicle) => ({ vehicle, filePage: wikimediaFilePageUrl(vehicle.thumbnail_url) }))
    .filter((row): row is { vehicle: Vehicle; filePage: string } => row.filePage !== null);

  return (
    <div className="mx-auto max-w-3xl px-4 pb-16 pt-8 sm:pt-10">
      <PageHeader
        title="Photo credits"
        subtitle="Car photos are from Wikimedia Commons under free licences. Each file page names the author and the licence."
      />
      <div className="mt-6">
        {error && (
          <EmptyState
            title="Could not load the photo credits"
            description="Please try again."
            action={<Button onClick={() => setReloadKey((key) => key + 1)}>Try again</Button>}
          />
        )}
        {!error && vehicles === null && <LoadingSkeleton className="h-40 w-full" />}
        {!error && vehicles !== null && credited.length === 0 && (
          <EmptyState title="No Commons photos yet" description="No car in the catalog uses a Wikimedia Commons photo." />
        )}
        {!error && credited.length > 0 && (
          <Card padding="md">
            <ul className="divide-y divide-border">
              {credited.map(({ vehicle, filePage }) => (
                <li key={vehicle.id} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-3">
                  <span className="text-small font-medium text-ink">
                    {vehicle.brand_name} {vehicle.name} {vehicle.trim}
                  </span>
                  <a
                    href={filePage}
                    target="_blank"
                    rel="noreferrer"
                    className="text-small font-medium text-primary-700 underline hover:text-primary-800"
                  >
                    Wikimedia Commons file page
                  </a>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    </div>
  );
}
