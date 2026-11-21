import { CatalogGrid } from "../components/catalog/CatalogGrid";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

export function CatalogPage() {
  useDocumentTitle("Vehicle Catalog");
  // The page title ("Browse cars", with the API's result count) is the grid's
  // PageHeader, because the count comes from the grid's own fetch.
  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:py-10">
      <CatalogGrid />
    </div>
  );
}
