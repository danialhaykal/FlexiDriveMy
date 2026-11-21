// Defaults shared by more than one screen, so two pages can never drift apart.

// The tenure every comparison screen (single car and Arena) opens on: 48
// months, the standard Hire Purchase / GFV term. Subscription runs for 12, 24
// or 36 months only, so at 48 it shows the server's own "Subscription plans
// run for ..." message instead of a price - a saved profile's preferred tenure
// still overrides this where the user has one.
export const DEFAULT_TENURE_MONTHS = 48;

// The vehicle page's "Monthly at a glance": 36 months is the longest tenure at
// which all three pathways (Hire Purchase, GFV and Subscription) are offered,
// so the buyer sees all three side by side. Its "See the full comparison"
// link opens the compare page on the same tenure, so the figures match.
export const QUICK_LOOK_TENURE_MONTHS = 36;
