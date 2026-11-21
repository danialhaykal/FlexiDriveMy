// "2026-02-15T00:00:00Z" -> "15 Feb 2026" (Malaysian English). Display only;
// an unparseable value is shown as given rather than guessed.
export function formatSavedDate(isoString: string): string {
  const date = new Date(isoString);
  if (Number.isNaN(date.getTime())) return isoString;
  return date.toLocaleDateString("en-MY", { day: "numeric", month: "short", year: "numeric" });
}
