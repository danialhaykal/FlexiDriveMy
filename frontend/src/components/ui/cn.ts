// Joins conditional class names, filtering out falsy values. This is not
// a Tailwind-conflict-resolving merge (no clsx/tailwind-merge dependency
// needed yet) - fine as long as a component's own variants never apply
// two different utilities for the same CSS property at once.
export function cn(...classes: Array<string | false | null | undefined>): string {
  return classes.filter(Boolean).join(" ");
}
