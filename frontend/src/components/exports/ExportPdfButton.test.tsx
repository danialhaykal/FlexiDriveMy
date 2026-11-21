import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ExportPdfButton, captureChartSvg, toRgb } from "./ExportPdfButton";
import { PdfExportError, exportComparisonPdf } from "../../api/exports";
import type { ComparisonResult } from "../../types/comparisons";

// Only the network call is mocked: parseExportErrorDetail keeps its real
// implementation, so the blob -> JSON -> message path is exercised.
vi.mock("../../api/exports", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/exports")>();
  return { ...actual, exportComparisonPdf: vi.fn() };
});

const mockedExport = vi.mocked(exportComparisonPdf);

function jsonBlob(body: unknown) {
  return new Blob([JSON.stringify(body)], { type: "application/json" });
}

function renderButton() {
  return render(
    <ExportPdfButton
      vehicleId={1}
      comparison={{} as ComparisonResult}
      tenureMonths={36}
      mileageBand="standard"
      downpayment="40000.00"
    />,
  );
}

describe("ExportPdfButton", () => {
  beforeEach(() => {
    mockedExport.mockReset();
  });

  // Run 1 fix batch 2 (G4): an oversize chart is a 400 with a field error.
  it("shows the API's own message on a 400, not the generic one", async () => {
    const message = "The chart is too large to include in the PDF. Please refresh the page and try again.";
    mockedExport.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 400, data: jsonBlob({ chart_svg: [message] }) },
    });

    renderButton();
    await userEvent.setup().click(screen.getByRole("button", { name: "Export as PDF" }));

    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.queryByText("Could not export the PDF. Please try again.")).not.toBeInTheDocument();
  });

  // Run 1 fix batch 5: with a real worker, a queued job that fails (or runs past
  // 60 s) ends with its own message, shown as-is.
  it("shows a queued job's own failure message", async () => {
    mockedExport.mockRejectedValueOnce(new PdfExportError("The PDF engine is unavailable right now."));

    renderButton();
    await userEvent.setup().click(screen.getByRole("button", { name: "Export as PDF" }));

    expect(await screen.findByText("The PDF engine is unavailable right now.")).toBeInTheDocument();
  });

  it("still shows a 504's detail message unchanged", async () => {
    mockedExport.mockRejectedValueOnce({
      isAxiosError: true,
      response: { status: 504, data: jsonBlob({ detail: "Please try downloading again." }) },
    });

    renderButton();
    await userEvent.setup().click(screen.getByRole("button", { name: "Export as PDF" }));

    expect(await screen.findByText("Please try downloading again.")).toBeInTheDocument();
  });
});


// Run 2 fix batch 1: the PDF engine has no app stylesheet, so a chart painted with
// stroke="var(--color-primary-600)" came out black. The capture writes the colour the
// browser actually drew onto a CLONE of the chart and leaves the page alone.
describe("captureChartSvg", () => {
  const CHART_HTML = `
    <div data-export-chart="tco-negative-equity">
      <div class="recharts-wrapper">
        <svg width="943" height="320" viewBox="0 0 943 320">
          <g class="grid"><line id="grid" stroke="var(--color-border)" x1="0" x2="10" /></g>
          <g class="axis">
            <line id="axis" stroke="var(--color-ink-muted)" x1="0" x2="10" />
            <text id="tick" fill="#666" stroke="none"><tspan x="72" dy="0.71em">0mo</tspan></text>
          </g>
          <path id="resale" stroke="var(--color-primary-600)" fill="none" d="M0 0L10 10" />
          <path id="balance" stroke="var(--color-danger-600)" fill="none" d="M0 10L10 0" />
          <text id="label" fill="var(--color-danger-700)">Negative equity</text>
        </svg>
      </div>
    </div>`;

  // What the browser says it drew for each element's paint.
  const DRAWN: Record<string, Record<string, string>> = {
    grid: { stroke: "rgb(226, 232, 240)" },
    axis: { stroke: "rgb(98, 116, 142)" },
    resale: { stroke: "rgb(79, 57, 246)" },
    balance: { stroke: "rgb(231, 0, 11)" },
    label: { fill: "rgb(193, 0, 7)" },
  };

  function useDrawnColours(drawn = DRAWN) {
    vi.spyOn(window, "getComputedStyle").mockImplementation(
      (element: Element) =>
        ({ getPropertyValue: (property: string) => drawn[element.id]?.[property] ?? "" }) as CSSStyleDeclaration,
    );
  }

  beforeEach(() => {
    document.body.innerHTML = CHART_HTML;
  });
  afterEach(() => {
    vi.restoreAllMocks();
    document.body.innerHTML = "";
  });

  it("resolves every var() paint to the drawn colour on the serialised copy", () => {
    useDrawnColours();

    const markup = captureChartSvg();

    expect(markup).not.toContain("var(");
    expect(markup).toContain('stroke="rgb(79, 57, 246)"');
    expect(markup).toContain('stroke="rgb(231, 0, 11)"');
    expect(markup).toContain('stroke="rgb(226, 232, 240)"');
    expect(markup).toContain('stroke="rgb(98, 116, 142)"');
    expect(markup).toContain('fill="rgb(193, 0, 7)"');
  });

  it("keeps the labels, the other paints and the viewBox as they were", () => {
    useDrawnColours();

    const markup = captureChartSvg();

    expect(markup).toContain('<tspan x="72" dy="0.71em">0mo</tspan>');
    expect(markup).toContain('fill="#666"');
    expect(markup).toContain('stroke="none"');
    expect(markup).toContain('viewBox="0 0 943 320"');
    expect(markup).toContain("Negative equity");
  });

  it("leaves the live chart exactly as it was", () => {
    useDrawnColours();
    const before = document.body.innerHTML;
    const resale = document.getElementById("resale")!;

    captureChartSvg();

    expect(document.body.innerHTML).toBe(before);
    expect(resale.getAttribute("stroke")).toBe("var(--color-primary-600)");
  });

  it("leaves a var() it cannot resolve as it is, so the server shows it grey rather than black", () => {
    useDrawnColours({ resale: { stroke: "rgb(79, 57, 246)" } });

    const markup = captureChartSvg();

    expect(markup).toContain('stroke="rgb(79, 57, 246)"');
    expect(markup).toContain('stroke="var(--color-danger-600)"');
  });

  it("returns an empty string when the chart is not on the page", () => {
    document.body.innerHTML = "<p>Financing Pathways tab</p>";

    expect(captureChartSvg()).toBe("");
  });

  it("turns an oklch colour (Tailwind v4's palette) into rgb() through a canvas", () => {
    useDrawnColours({ resale: { stroke: "oklch(0.511 0.262 276.966)" } });
    const context = {
      canvas: { width: 0, height: 0 },
      clearRect: vi.fn(),
      fillRect: vi.fn(),
      fillStyle: "",
      getImageData: vi.fn(() => ({ data: new Uint8ClampedArray([79, 57, 246, 255]) })),
    };
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(context as never);

    const markup = captureChartSvg();

    expect(context.fillStyle).toBe("oklch(0.511 0.262 276.966)");
    expect(markup).toContain('stroke="rgb(79, 57, 246)"');
    expect(markup).not.toContain("oklch");
  });
});

describe("toRgb", () => {
  afterEach(() => vi.restoreAllMocks());

  it.each(["rgb(1, 2, 3)", "rgba(1, 2, 3, 0.5)", "#4f39f6", "#fff", "none", "currentColor", "url(#g1)", ""])(
    "passes %j through untouched without touching a canvas",
    (value) => {
      const getContext = vi.spyOn(HTMLCanvasElement.prototype, "getContext");

      expect(toRgb(value)).toBe(value);
      expect(getContext).not.toHaveBeenCalled();
    },
  );

  function fakeCanvas(pixel: number[]) {
    const context = {
      canvas: { width: 0, height: 0 },
      clearRect: vi.fn(),
      fillRect: vi.fn(),
      fillStyle: "",
      getImageData: vi.fn(() => ({ data: new Uint8ClampedArray(pixel) })),
    };
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(context as never);
    return context;
  }

  it("reads an opaque colour back as rgb()", () => {
    fakeCanvas([231, 0, 11, 255]);

    expect(toRgb("oklch(0.577 0.245 27.325)")).toBe("rgb(231, 0, 11)");
  });

  it("reads a translucent colour back as rgba()", () => {
    fakeCanvas([0, 0, 0, 128]);

    expect(toRgb("oklch(0 0 0 / 50%)")).toBe("rgba(0, 0, 0, 0.502)");
  });

  it("gives the value back when there is no canvas or it throws", () => {
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    expect(toRgb("oklch(0.5 0.2 270)")).toBe("oklch(0.5 0.2 270)");

    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockImplementation(() => {
      throw new Error("no canvas");
    });
    expect(toRgb("oklch(0.5 0.2 270)")).toBe("oklch(0.5 0.2 270)");
  });
});

// FX-2 (item 13): the download uses the file name the server sent.
describe("ExportPdfButton file name", () => {
  it("saves the PDF under the server's name, and the old name only when none was sent", async () => {
    const names: string[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      names.push(this.download);
    });
    const createUrl = vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:x");
    const revokeUrl = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
    mockedExport
      .mockResolvedValueOnce({ blob: new Blob(["%PDF"]), filename: "FlexiDriveMy_BMW-3-Series_36m_2026-11-02.pdf" })
      .mockResolvedValueOnce({ blob: new Blob(["%PDF"]), filename: null });
    const user = userEvent.setup();

    renderButton();
    await user.click(screen.getByRole("button", { name: "Export as PDF" }));
    await screen.findByText("Your PDF download has started.");
    await user.click(screen.getByRole("button", { name: "Export as PDF" }));

    await vi.waitFor(() =>
      expect(names).toEqual(["FlexiDriveMy_BMW-3-Series_36m_2026-11-02.pdf", "comparison_report_1.pdf"]),
    );
    click.mockRestore();
    createUrl.mockRestore();
    revokeUrl.mockRestore();
  });
});
