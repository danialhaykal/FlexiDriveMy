// FX-2 (item 4): the tenure slider's labelled ticks and its "not offered" hint,
// shared by the compare page and Compare Cars. The slider still allows any
// month 12-108; the ticks are the terms where every option is offered.
export const TENURE_MARKS = [12, 24, 36, 48, 60];

type Unavailable = Partial<Record<string, string>> | null | undefined;

// The API's own "not offered" sentences for GFV and Subscription - from one
// comparison, or from several (Compare Cars), each distinct sentence once.
// Nothing here decides availability; it only repeats what the API said.
export function notOfferedHint(...unavailable: Unavailable[]): string | undefined {
  const reasons: string[] = [];
  for (const entry of unavailable) {
    for (const reason of [entry?.gfv_leasing, entry?.subscription]) {
      if (reason && !reasons.includes(reason)) reasons.push(reason);
    }
  }
  return reasons.length > 0 ? reasons.join(" ") : undefined;
}
