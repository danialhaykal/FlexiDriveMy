import { Link } from "react-router-dom";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { PageHeader } from "../components/ui/PageHeader";
import { cn } from "../components/ui/cn";

const LINK_BUTTON =
  "inline-flex items-center justify-center rounded-control px-4 py-2 text-small font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500";

// FX-2 (item 9): an unknown address says so, instead of silently opening the dashboard.
export function NotFoundPage() {
  useDocumentTitle("Page not found");
  return (
    <div className="mx-auto max-w-3xl px-4 pb-16 pt-8 sm:pt-10">
      <PageHeader title="Page not found" subtitle="We couldn't find that page. The link may be wrong or out of date." />
      <div className="mt-6 flex flex-wrap gap-3">
        <Link to="/" className={cn(LINK_BUTTON, "bg-primary-600 text-white hover:bg-primary-700")}>
          Go to dashboard
        </Link>
        <Link to="/catalog" className={cn(LINK_BUTTON, "border border-border bg-surface text-ink hover:bg-surface-subtle")}>
          Browse cars
        </Link>
      </div>
    </div>
  );
}
