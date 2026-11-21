import { useEffect, useState } from "react";
import axios from "axios";
import { PdfExportError, exportComparisonPdf, parseExportErrorDetail } from "../../api/exports";
import type { ComparisonResult, MileageBand } from "../../types/comparisons";
import { Button } from "../ui/Button";

// F008 / UC008 "Export as PDF". Sends only the same inputs the
// Financing Pathways tab itself used (vehicle/tenure/mileage/
// downpayment) - the server recomputes the actual pathway figures
// itself rather than trusting whatever this component might send (QA
// audit C4), so this component never reads pathway data out of
// `comparison`, it only uses it to gate the button: disabled until a
// successful comparison result exists for these exact inputs.

interface ExportPdfButtonProps {
  vehicleId: number;
  comparison: ComparisonResult | null;
  tenureMonths: number;
  mileageBand: MileageBand;
  downpayment: string;
}

const GENERIC_ERROR = "Could not export the PDF. Please try again.";
const CONFIRMATION_DURATION_MS = 4000;

// QA audit M16: matches the data attribute NegativeEquityChart renders
// on its chart container. That container only exists in the DOM while
// the TCO tab is the active Tabs.Panel (inactive panels unmount, see
// components/ui/Tabs.tsx) - so this selector doubles as the "is a chart
// currently available" check. Run 1 fix batch 2: `.recharts-wrapper > svg`,
// not just `svg` - Recharts renders the legend's small icon <svg>s BEFORE
// the chart itself, so a bare `svg` captured a 14x14 legend icon instead
// of the chart.
export const CHART_EXPORT_SELECTOR = '[data-export-chart="tco-negative-equity"] .recharts-wrapper > svg';

// Run 2 fix batch 1: the chart paints with CSS variables
// (stroke="var(--color-primary-600)"). The PDF engine has no app stylesheet, so
// an unresolved var(...) paints black. The capture therefore writes the colour
// the browser actually drew onto the CLONE. Tailwind v4's palette is oklch, which
// getComputedStyle can hand back as an "oklch(...)" string the PDF side does not
// accept, so any colour that is not already hex/rgb is normalised to rgb()
// through a 1x1 canvas. Values it cannot normalise are left as they are; the
// server then replaces them with a visible grey (apps/exports/svg_sanitizer.py).
const PAINT_ATTRIBUTES = ["stroke", "fill"] as const;

export function toRgb(color: string): string {
  const value = color.trim();
  if (value === "" || /^(#|rgb|none$|currentcolor$|url\()/i.test(value)) return value;
  try {
    const context = document.createElement("canvas").getContext("2d");
    if (!context) return value;
    context.canvas.width = 1;
    context.canvas.height = 1;
    context.clearRect(0, 0, 1, 1);
    context.fillStyle = value;
    context.fillRect(0, 0, 1, 1);
    const [r, g, b, a] = context.getImageData(0, 0, 1, 1).data;
    return a === 255 ? `rgb(${r}, ${g}, ${b})` : `rgba(${r}, ${g}, ${b}, ${Number((a / 255).toFixed(3))})`;
  } catch {
    return value;
  }
}

// Captures the live, currently-rendered chart's SVG markup for the PDF.
// Returns "" - never throws, never fabricates markup - when the user
// isn't on the TCO tab at export time, so the export still proceeds
// with the chart section simply omitted (see rendering.py's
// build_report_html), rather than blocking or silently guessing.
// It serialises a CLONE with its var() paints resolved, never the live node,
// so the page itself is left exactly as it was.
export function captureChartSvg(): string {
  const live = document.querySelector(CHART_EXPORT_SELECTOR);
  if (!live) return "";
  const clone = live.cloneNode(true) as Element;
  const liveNodes = [live, ...live.querySelectorAll("*")];
  const cloneNodes = [clone, ...clone.querySelectorAll("*")];
  liveNodes.forEach((liveNode, index) => {
    const cloneNode = cloneNodes[index];
    for (const attribute of PAINT_ATTRIBUTES) {
      if (!cloneNode.getAttribute(attribute)?.includes("var(")) continue;
      const drawn = window.getComputedStyle(liveNode).getPropertyValue(attribute);
      if (drawn.trim() !== "") cloneNode.setAttribute(attribute, toRgb(drawn));
    }
  });
  return new XMLSerializer().serializeToString(clone);
}

export function ExportPdfButton({
  vehicleId,
  comparison,
  tenureMonths,
  mileageBand,
  downpayment,
}: ExportPdfButtonProps) {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<string | null>(null);

  useEffect(() => {
    if (!confirmation) return;
    const timer = setTimeout(() => setConfirmation(null), CONFIRMATION_DURATION_MS);
    return () => clearTimeout(timer);
  }, [confirmation]);

  // QA audit L3: a stale error from a PREVIOUS export attempt (e.g. a
  // timeout at the old tenure) otherwise stayed on screen indefinitely
  // after the user changed an input and got a fresh, successful
  // comparison - this component is never unmounted by an input change
  // (only `comparison` itself gets recomputed), so nothing else would
  // ever clear it.
  useEffect(() => {
    setError(null);
  }, [tenureMonths, mileageBand, downpayment]);

  const handleExport = async () => {
    if (!comparison) return;
    setIsLoading(true);
    setError(null);
    setConfirmation(null);
    try {
      const { blob, filename } = await exportComparisonPdf({
        vehicle: vehicleId,
        tenureMonths,
        mileageBand,
        downpayment,
        chartSvg: captureChartSvg(),
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      // FX-2 (item 13): the server's own name; the old one only if it sent none.
      link.download = filename ?? `comparison_report_${vehicleId}.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      setConfirmation("Your PDF download has started.");
    } catch (err: unknown) {
      if (err instanceof PdfExportError) {
        // A queued export that failed (its own message) or ran past 60 s.
        setError(err.message);
      } else if (axios.isAxiosError(err) && err.response) {
        setError(await parseExportErrorDetail(err.response.data));
      } else {
        setError(GENERIC_ERROR);
      }
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="flex flex-col items-start gap-2">
      <Button variant="secondary" onClick={handleExport} isLoading={isLoading} disabled={!comparison}>
        Export as PDF
      </Button>
      {confirmation && (
        <p role="status" className="text-small text-positive-700">
          {confirmation}
        </p>
      )}
      {error && (
        <p role="alert" className="text-small text-danger-700">
          {error}
        </p>
      )}
    </div>
  );
}
