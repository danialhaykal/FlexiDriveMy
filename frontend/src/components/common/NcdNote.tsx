// Run 1 fix batch 3: the server applies the buyer's No-Claim Discount (from
// their Financial Profile) to the owner's insurance and reports which one it
// used as `ncd_percent`. When that is "0.00" the insurance shown is the
// before-NCD figure, so say so. Nothing is shown for a saved snapshot from
// before NCD existed (no `ncd_percent` at all), and nothing is computed here.

export const BEFORE_NCD_NOTE = "Insurance shown before No-Claim Discount. Add your NCD in Financial Profile.";

export function isBeforeNcd(ncdPercent: string | undefined): boolean {
  return ncdPercent === "0.00";
}

export function NcdNote({ ncdPercent, className }: { ncdPercent: string | undefined; className?: string }) {
  if (!isBeforeNcd(ncdPercent)) return null;
  return <p className={className ?? "text-caption text-ink-muted"}>{BEFORE_NCD_NOTE}</p>;
}
