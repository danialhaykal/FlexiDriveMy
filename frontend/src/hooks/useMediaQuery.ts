import { useEffect, useState } from "react";

// True while the CSS media query matches, updated as the window resizes. For
// a layout that cannot be one DOM restyled by CSS (the Arena: a table with
// one column per car from md, one card per car below it) - so each figure is
// in the page once, never twice with one copy hidden.
//
// `fallback` is used where the browser has no matchMedia (jsdom in tests).
//
// Usage: const isWide = useMediaQuery("(min-width: 768px)", true);

export function useMediaQuery(query: string, fallback: boolean): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia(query).matches
      : fallback,
  );

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const list = window.matchMedia(query);
    const update = () => setMatches(list.matches);
    update();
    list.addEventListener("change", update);
    return () => list.removeEventListener("change", update);
  }, [query]);

  return matches;
}
