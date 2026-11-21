import { Link } from "react-router-dom";
import { wikimediaFilePageUrl } from "../../lib/wikimediaCredit";

// FX-2 (item 8): one line under a list of cars with photos, pointing to the
// Credits page (author and licence are on each Commons file page). Shown only
// when at least one listed car has a Commons photo.
export function PhotoCreditLine({ thumbnailUrls }: { thumbnailUrls: (string | null | undefined)[] }) {
  if (!thumbnailUrls.some((url) => wikimediaFilePageUrl(url) !== null)) return null;
  return (
    <p className="text-caption text-ink-muted">
      Photos: Wikimedia Commons (
      <Link to="/credits" className="font-medium text-primary-700 underline hover:text-primary-800">
        see credits
      </Link>
      )
    </p>
  );
}
