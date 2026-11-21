import { beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "./client";
import { PDF_STILL_RUNNING_MESSAGE, PdfExportError, exportComparisonPdf } from "./exports";

// Run 1 fix batch 5: PDF export in both modes. The network is mocked; the
// 2-second wait is replaced by a no-op so the 60-second limit is counted in
// polls (30), not real time.

vi.mock("./client", () => ({
  apiClient: { post: vi.fn(), get: vi.fn() },
}));

const mockedPost = vi.mocked(apiClient.post);
const mockedGet = vi.mocked(apiClient.get);
const noWait = vi.fn(() => Promise.resolve());
const PARAMS = { vehicle: 5, tenureMonths: 36, mileageBand: "standard" as const, downpayment: "26580.00" };

function jsonBlob(body: unknown) {
  return new Blob([JSON.stringify(body)], { type: "application/json" });
}

describe("exportComparisonPdf", () => {
  beforeEach(() => {
    mockedPost.mockReset();
    mockedGet.mockReset();
    noWait.mockClear();
  });

  // FX-2 (item 13): the result is { blob, filename } (it was the Blob alone); the name is the server's.
  it("eager mode: returns the PDF and the server's file name from the same response, with no polling", async () => {
    const pdf = new Blob(["%PDF"], { type: "application/pdf" });
    mockedPost.mockResolvedValueOnce({
      status: 200,
      data: pdf,
      headers: { "content-disposition": 'attachment; filename="FlexiDriveMy_BMW-3-Series_36m_2026-11-02.pdf"' },
    });

    await expect(exportComparisonPdf(PARAMS, noWait)).resolves.toEqual({
      blob: pdf,
      filename: "FlexiDriveMy_BMW-3-Series_36m_2026-11-02.pdf",
    });
    expect(mockedGet).not.toHaveBeenCalled();
  });

  it("a real worker: on 202 it polls every 2 s, then downloads the finished PDF", async () => {
    const pdf = new Blob(["%PDF from the worker"], { type: "application/pdf" });
    mockedPost.mockResolvedValueOnce({ status: 202, data: jsonBlob({ job_id: 41, status: "pending" }) });
    mockedGet
      .mockResolvedValueOnce({ data: { job_id: 41, status: "running", detail: null } })
      .mockResolvedValueOnce({ data: { job_id: 41, status: "succeeded", detail: null } })
      .mockResolvedValueOnce({ data: pdf, headers: {} });

    await expect(exportComparisonPdf(PARAMS, noWait)).resolves.toEqual({ blob: pdf, filename: null });
    expect(noWait).toHaveBeenCalledTimes(2);
    expect(noWait).toHaveBeenCalledWith(2000);
    expect(mockedGet).toHaveBeenNthCalledWith(1, "/exports/pdf/41/");
    expect(mockedGet).toHaveBeenLastCalledWith("/exports/pdf/41/download/", { responseType: "blob" });
  });

  it("a failed job ends the wait with the job's own message", async () => {
    mockedPost.mockResolvedValueOnce({ status: 202, data: jsonBlob({ job_id: 41, status: "pending" }) });
    mockedGet.mockResolvedValueOnce({
      data: { job_id: 41, status: "failed", detail: "PDF generation timed out. Please try downloading again." },
    });

    await expect(exportComparisonPdf(PARAMS, noWait)).rejects.toEqual(
      new PdfExportError("PDF generation timed out. Please try downloading again."),
    );
  });

  it("gives up after 60 s (30 polls) with a plain message", async () => {
    mockedPost.mockResolvedValueOnce({ status: 202, data: jsonBlob({ job_id: 41, status: "pending" }) });
    mockedGet.mockResolvedValue({ data: { job_id: 41, status: "running", detail: null } });

    await expect(exportComparisonPdf(PARAMS, noWait)).rejects.toEqual(new PdfExportError(PDF_STILL_RUNNING_MESSAGE));
    expect(noWait).toHaveBeenCalledTimes(30);
  });
});
