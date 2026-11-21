// Design-system constants components need as plain TypeScript values, not
// CSS custom properties. Color/spacing/type tokens themselves live in
// src/index.css's @theme block - import from there via Tailwind utility
// classes; import from here only for a value TS code needs directly.

// Tabular-nums keeps digits a fixed width so numbers in adjacent rows -
// especially RM currency figures - align into clean columns instead of
// drifting with each digit's natural width. Apply this to every rendered
// numeric/currency value across the app. Table's `numeric` cell/header
// prop already applies it for table columns.
export const numeric = "tabular-nums";

// Shared vocabulary for financial/system status - see Badge.
export type Tone = "positive" | "warning" | "danger" | "neutral" | "recommended" | "estimate";
