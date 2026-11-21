// Run 3 fix batch 4 (F-17): shown under an admin table only when the list was
// cut short by the all-pages safety cap (api/allPages.ts) - never otherwise.
// `total` is the server's row count captured when the list was loaded
// (listTotal), `shown` the rows on screen.
//
// Usage: <ListCapNotice shown={vehicles.length} total={vehiclesTotal} />

interface ListCapNoticeProps {
  shown: number;
  total: number;
}

export function ListCapNotice({ shown, total }: ListCapNoticeProps) {
  if (total <= shown) return null;
  return (
    <p role="status" className="mt-2 text-caption text-warning-700">
      Showing {shown.toLocaleString("en-MY")} of {total.toLocaleString("en-MY")} rows.
    </p>
  );
}
