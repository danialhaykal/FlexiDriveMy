import { renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useDocumentTitle } from "./useDocumentTitle";

describe("useDocumentTitle", () => {
  it("sets the document title with the app name suffixed", () => {
    renderHook(() => useDocumentTitle("Catalog"));
    expect(document.title).toBe("Catalog - FlexiDriveMy");
  });

  it("updates when the title changes", () => {
    const { rerender } = renderHook(({ title }) => useDocumentTitle(title), {
      initialProps: { title: "Catalog" },
    });
    rerender({ title: "Vehicle detail" });
    expect(document.title).toBe("Vehicle detail - FlexiDriveMy");
  });

  it("restores the previous title on unmount", () => {
    document.title = "Something else";
    const { unmount } = renderHook(() => useDocumentTitle("Catalog"));
    expect(document.title).toBe("Catalog - FlexiDriveMy");
    unmount();
    expect(document.title).toBe("Something else");
  });
});
