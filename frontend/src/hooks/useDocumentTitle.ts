import { useEffect } from "react";

// Cosmetic: every page previously left the browser tab title at the
// static "FlexiDriveMy" from index.html - this sets it per page (and
// restores the previous title on unmount, so navigating between pages
// doesn't leave a stale title from whichever page set one last if a
// page ever renders without calling this).
export function useDocumentTitle(title: string): void {
  useEffect(() => {
    const previousTitle = document.title;
    document.title = `${title} - FlexiDriveMy`;
    return () => {
      document.title = previousTitle;
    };
  }, [title]);
}
