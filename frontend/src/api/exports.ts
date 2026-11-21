import { apiClient } from "./client";
import { parseApiErrorMessage } from "../lib/apiErrors";
import type { MileageBand } from "../types/comparisons";

const GENERIC_EXPORT_ERROR = "Could not export the PDF. Please try again.";

export interface ExportPdfParams {
  vehicle: number;
  tenureMonths: number;
  mileageBand: MileageBand;
  downpayment: string;
  // QA audit M16: the live TCO chart's SVG markup, captured by the
  // caller at click time - "" when no chart is currently mounted (the
  // user isn't on the TCO tab), never fabricated here.
  chartSvg?: string;
}

// POST /api/exports/pdf/ (F008 / UC008) - server renders and streams
// back the actual PDF bytes. Sends only the SAME inputs F005's own
// comparison endpoint takes - never pathway figures themselves (QA audit
// C4: the backend now recomputes those itself via build_comparison, the
// same single source of truth every other endpoint uses, rather than
// trusting whatever a client claims a pathway's monthly instalment was).
// responseType: "blob" is required since a successful response body is
// binary - see parseExportErrorDetail below for the consequence of that
// on failure responses.
// Run 1 fix batch 5: a failure the button shows as-is (a failed job's own
// message, or the 60-second wait running out).
export class PdfExportError extends Error {}

export const PDF_POLL_INTERVAL_MS = 2000;
export const PDF_MAX_WAIT_MS = 60000;
export const PDF_STILL_RUNNING_MESSAGE =
  "The PDF is taking longer than expected. Please try downloading again in a minute.";

interface PdfJobStatus {
  job_id: number;
  status: "pending" | "running" | "succeeded" | "failed";
  detail: string | null;
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

// FX-2 (item 13): the PDF and the file name the server chose for it
// (FlexiDriveMy_{brand}-{model}_{tenure}m_{date}.pdf, from Content-Disposition;
// null if the header is missing, e.g. an older server).
export interface ExportedPdf {
  blob: Blob;
  filename: string | null;
}

export function filenameFromContentDisposition(header: unknown): string | null {
  if (typeof header !== "string") return null;
  const match = /filename="([^"]+)"/.exec(header);
  return match ? match[1] : null;
}

export async function exportComparisonPdf(
  params: ExportPdfParams,
  wait: (ms: number) => Promise<void> = sleep,
): Promise<ExportedPdf> {
  const response = await apiClient.post<Blob>(
    "/exports/pdf/",
    {
      vehicle: params.vehicle,
      tenure_months: params.tenureMonths,
      mileage_band: params.mileageBand,
      downpayment: params.downpayment,
      chart_svg: params.chartSvg ?? "",
    },
    { responseType: "blob" },
  );
  // Eager mode (dev, the demo): the PDF itself came back. With a real Celery
  // worker the server answers 202 {job_id, status}: poll every 2 s for up to
  // 60 s, then download it.
  if (response.status !== 202) {
    return { blob: response.data, filename: filenameFromContentDisposition(response.headers?.["content-disposition"]) };
  }
  const { job_id: jobId } = JSON.parse(await response.data.text()) as PdfJobStatus;
  for (let waited = 0; waited < PDF_MAX_WAIT_MS; waited += PDF_POLL_INTERVAL_MS) {
    await wait(PDF_POLL_INTERVAL_MS);
    const { data: job } = await apiClient.get<PdfJobStatus>(`/exports/pdf/${jobId}/`);
    if (job.status === "succeeded") {
      const download = await apiClient.get<Blob>(`/exports/pdf/${jobId}/download/`, { responseType: "blob" });
      return { blob: download.data, filename: filenameFromContentDisposition(download.headers?.["content-disposition"]) };
    }
    if (job.status === "failed") {
      throw new PdfExportError(job.detail ?? GENERIC_EXPORT_ERROR);
    }
  }
  throw new PdfExportError(PDF_STILL_RUNNING_MESSAGE);
}

// Because the request used responseType: "blob", a non-2xx response's
// JSON body (e.g. UC008's 504 timeout message) arrives as a Blob too,
// not parsed JSON - axios only decodes error.response.data according to
// the responseType that was set, regardless of status code. Read the
// blob as text and parse it ourselves; fall back to a generic message if
// that fails for any reason. A 400's message is usually a field error
// (e.g. { chart_svg: ["The chart is too large ..."] }), not `.detail`, so
// the shared parser reads both shapes.
export async function parseExportErrorDetail(data: unknown): Promise<string> {
  if (!(data instanceof Blob)) return GENERIC_EXPORT_ERROR;
  try {
    const text = await data.text();
    return parseApiErrorMessage(JSON.parse(text)) ?? GENERIC_EXPORT_ERROR;
  } catch {
    return GENERIC_EXPORT_ERROR;
  }
}
