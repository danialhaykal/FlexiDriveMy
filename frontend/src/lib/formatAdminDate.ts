// FX-3 (X13): one date format on every admin page, in the viewer's local time:
// "30 Oct 2026" for a date, "30 Oct 2026, 2:18 pm" where a time is shown.
// Display only; an unparseable value is shown as given rather than guessed.

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

function toDate(value: string): Date | null {
  // A date-only value ("2026-01-01", e.g. effective_from) is a calendar day,
  // not UTC midnight - read it as that day locally so it never shifts.
  const match = DATE_ONLY.exec(value);
  const date = match ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function parts(date: Date, withTime: boolean): Record<string, string> {
  const format = new Intl.DateTimeFormat("en-MY", {
    day: "numeric",
    month: "short",
    year: "numeric",
    ...(withTime ? { hour: "numeric", minute: "2-digit", hour12: true } : {}),
  });
  return Object.fromEntries(format.formatToParts(date).map((part) => [part.type, part.value]));
}

export function formatAdminDate(value: string | null | undefined): string {
  if (!value) return "";
  const date = toDate(value);
  if (!date) return value;
  const p = parts(date, false);
  return `${p.day} ${p.month} ${p.year}`;
}

export function formatAdminDateTime(value: string | null | undefined): string {
  if (!value) return "";
  const date = toDate(value);
  if (!date) return value;
  const p = parts(date, true);
  return `${p.day} ${p.month} ${p.year}, ${p.hour}:${p.minute} ${(p.dayPeriod ?? "").toLowerCase()}`.trim();
}
