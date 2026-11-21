import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AdminAuditLogPage, NOTHING_BEFORE, NOTHING_RECORDED } from "./AdminAuditLogPage";
import { fetchAuditLogs } from "../api/audit";
import type { AuditLog, AuditLogListResponse } from "../types/audit";

vi.mock("../api/audit", () => ({
  fetchAuditLogs: vi.fn(),
}));

const mockedFetchAuditLogs = vi.mocked(fetchAuditLogs);

function makeLog(overrides: Partial<AuditLog> = {}): AuditLog {
  return {
    id: 1,
    actor_id: 7,
    actor_email: "admin@example.com",
    timestamp: "2026-01-15T09:30:00Z",
    action: "update",
    resource_type: "policy.InterestRate",
    resource_id: "1",
    ip_address: "127.0.0.1",
    before_data: { rate_percent: "3.0000" },
    after_data: { rate_percent: "3.5000" },
    ...overrides,
  };
}

function page(results: AuditLog[], overrides: Partial<AuditLogListResponse> = {}): AuditLogListResponse {
  return { count: results.length, next: null, previous: null, results, ...overrides };
}

// Redesign UI-6b: an action badge (the Action filter's options carry the same words).
const badgeWithText = (text: string) => screen.getAllByText(text).find((el) => el.hasAttribute("data-tone"));

describe("AdminAuditLogPage", () => {
  beforeEach(() => {
    mockedFetchAuditLogs.mockReset();
  });

  it("loads and renders audit log rows on mount with no filters", async () => {
    mockedFetchAuditLogs.mockResolvedValueOnce(page([makeLog()]));

    render(<AdminAuditLogPage />);

    expect(await screen.findByText("admin@example.com")).toBeInTheDocument();
    expect(mockedFetchAuditLogs).toHaveBeenCalledWith(
      { actor_email: "", action: "", resource_type: "", timestamp_from: "", timestamp_to: "" },
      1,
    );
  });

  it("expands a row to show the pretty-printed before/after delta", async () => {
    mockedFetchAuditLogs.mockResolvedValueOnce(page([makeLog()]));
    const user = userEvent.setup();

    render(<AdminAuditLogPage />);
    const timestampButton = await screen.findByRole("button", { name: /2026/ });
    await user.click(timestampButton);

    expect(screen.getByText(/"rate_percent": "3.0000"/)).toBeInTheDocument();
    expect(screen.getByText(/"rate_percent": "3.5000"/)).toBeInTheDocument();
  });

  it("re-fetches with the entered filters when Apply Filters is submitted", async () => {
    mockedFetchAuditLogs.mockResolvedValue(page([makeLog()]));
    const user = userEvent.setup();

    render(<AdminAuditLogPage />);
    await screen.findByText("admin@example.com");

    await user.type(screen.getByLabelText("User email"), "admin@example.com");
    await user.click(screen.getByRole("button", { name: "Apply Filters" }));

    expect(mockedFetchAuditLogs).toHaveBeenLastCalledWith(
      expect.objectContaining({ actor_email: "admin@example.com" }),
      1,
    );
  });

  // --- Audit batch 6b: an admin thinks in emails, not ids --------------------

  it("filters by user email: no 'Actor ID' box, an email box with its own placeholder", async () => {
    mockedFetchAuditLogs.mockResolvedValue(page([makeLog()]));

    render(<AdminAuditLogPage />);
    await screen.findByText("admin@example.com");

    expect(screen.queryByLabelText("Actor ID")).not.toBeInTheDocument();
    expect(screen.getByLabelText("User email")).toHaveAttribute("placeholder", "Filter by user email");
  });

  it("clears the email box when the filters are reset, and reloads without it", async () => {
    mockedFetchAuditLogs.mockResolvedValue(page([makeLog()]));
    const user = userEvent.setup();

    render(<AdminAuditLogPage />);
    await screen.findByText("admin@example.com");
    await user.type(screen.getByLabelText("User email"), "nobody@example.com");

    await user.click(screen.getByRole("button", { name: "Reset" }));

    expect(screen.getByLabelText("User email")).toHaveValue("");
    expect(mockedFetchAuditLogs).toHaveBeenLastCalledWith(expect.objectContaining({ actor_email: "" }), 1);
  });

  it("shows the empty state, not an error, for an email no one used", async () => {
    mockedFetchAuditLogs.mockResolvedValueOnce(page([makeLog()])).mockResolvedValueOnce(page([]));
    const user = userEvent.setup();

    render(<AdminAuditLogPage />);
    await screen.findByText("admin@example.com");
    await user.type(screen.getByLabelText("User email"), "nobody@example.com");
    await user.click(screen.getByRole("button", { name: "Apply Filters" }));

    expect(await screen.findByText("No matching audit log entries")).toBeInTheDocument();
    expect(screen.queryByText("Could not load audit log entries. Please try again.")).not.toBeInTheDocument();
  });

  // Live-walkthrough finding 4: reported as "selecting Archive in the
  // Action dropdown, then clicking Apply Filters, sends zero requests."
  // This exercises exactly that interaction (the native <select>, not
  // the user-email text input the test above already covers) via realistic
  // simulated DOM events - a reproduction attempt in this environment,
  // not an assumption either way.
  it("re-fetches with the Action filter when 'Archive' is selected and Apply Filters is submitted", async () => {
    mockedFetchAuditLogs.mockResolvedValue(page([makeLog()]));
    const user = userEvent.setup();

    render(<AdminAuditLogPage />);
    await screen.findByText("admin@example.com");
    const callsBeforeSubmit = mockedFetchAuditLogs.mock.calls.length;

    await user.selectOptions(screen.getByLabelText("Action"), "archive");
    expect(screen.getByLabelText("Action")).toHaveValue("archive");
    await user.click(screen.getByRole("button", { name: "Apply Filters" }));

    expect(mockedFetchAuditLogs.mock.calls.length).toBeGreaterThan(callsBeforeSubmit);
    expect(mockedFetchAuditLogs).toHaveBeenLastCalledWith(
      expect.objectContaining({ action: "archive" }),
      1,
    );
  });

  it("shows the server's exact 504 timeout message, not a generic error", async () => {
    mockedFetchAuditLogs.mockRejectedValueOnce({
      isAxiosError: true,
      response: {
        status: 504,
        data: { detail: "Log query timed out. Please specify a narrower date range filter." },
      },
    });

    render(<AdminAuditLogPage />);

    expect(
      await screen.findByText("Log query timed out. Please specify a narrower date range filter."),
    ).toBeInTheDocument();
  });

  it("disables Previous on the first page and enables Next when more pages exist", async () => {
    mockedFetchAuditLogs.mockResolvedValueOnce(
      page([makeLog()], { next: "http://api/audit/logs/?page=2", previous: null, count: 50 }),
    );

    render(<AdminAuditLogPage />);
    await screen.findByText("admin@example.com");

    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next" })).toBeEnabled();
  });

  // --- Run 1 fix batch 4: system runtime errors --------------------------------

  const RUNTIME_ERROR = makeLog({
    id: 2,
    actor_id: null,
    actor_email: "",
    action: "runtime_error",
    resource_type: "system.error",
    resource_id: "pdf_export",
    ip_address: null,
    before_data: null,
    after_data: {
      error_type: "PDFCompilationTimeoutError",
      message: "PDF compilation exceeded 30s",
      path: "",
      method: "",
      status: 504,
      context: { job_id: 12, failure_reason: "timeout" },
    },
  });

  it("offers 'Runtime error' in the Action filter and sends it", async () => {
    mockedFetchAuditLogs.mockResolvedValue(page([RUNTIME_ERROR]));
    const user = userEvent.setup();

    render(<AdminAuditLogPage />);
    await screen.findByText("System error");
    await user.selectOptions(screen.getByLabelText("Action"), "runtime_error");
    await user.click(screen.getByRole("button", { name: "Apply Filters" }));

    const option = screen.getByRole("option", { name: "Runtime error" }) as HTMLOptionElement;
    expect(option.value).toBe("runtime_error");
    expect(mockedFetchAuditLogs).toHaveBeenLastCalledWith(expect.objectContaining({ action: "runtime_error" }), 1);
  });

  it("marks an error row with a red Error badge and shows its details", async () => {
    mockedFetchAuditLogs.mockResolvedValueOnce(page([makeLog(), RUNTIME_ERROR]));
    const user = userEvent.setup();

    render(<AdminAuditLogPage />);
    const badge = await screen.findByText("Error");
    expect(badge).toHaveAttribute("data-tone", "danger");
    // Redesign UI-6b: the action's label, not its raw key (was "update"); the Action
    // filter lists the same word, so the badge is the element with a tone.
    expect(badgeWithText("Update")).toHaveAttribute("data-tone", "neutral");

    const errorRow = screen.getByText("System error").closest("tr") as HTMLElement;
    await user.click(errorRow.querySelector("button") as HTMLElement);

    expect(screen.getByText(/"error_type": "PDFCompilationTimeoutError"/)).toBeInTheDocument();
    expect(screen.getByText(/"failure_reason": "timeout"/)).toBeInTheDocument();
    // Read-only: no edit or delete controls on any row.
    expect(screen.queryByRole("button", { name: /delete|edit/i })).not.toBeInTheDocument();
  });

  // --- Run 3 fix batch 5 (F-30a) ------------------------------------------------

  it("says 'Nothing before (new record)' for a create instead of a bare null", async () => {
    mockedFetchAuditLogs.mockResolvedValueOnce(page([makeLog({ action: "create", before_data: null })]));
    const user = userEvent.setup();

    render(<AdminAuditLogPage />);
    await user.click(await screen.findByRole("button", { name: /2026/ }));

    expect(screen.getByText(NOTHING_BEFORE)).toBeInTheDocument();
    expect(NOTHING_BEFORE).toBe("Nothing before (new record)");
    expect(screen.queryByText("null")).not.toBeInTheDocument();
    expect(screen.getByText(/"rate_percent": "3.5000"/)).toBeInTheDocument(); // After unchanged
  });

  it("says 'Nothing recorded' for another row with no before data", async () => {
    mockedFetchAuditLogs.mockResolvedValueOnce(page([RUNTIME_ERROR]));
    const user = userEvent.setup();

    render(<AdminAuditLogPage />);
    await user.click(await screen.findByRole("button", { name: /2026/ }));

    expect(screen.getByText(NOTHING_RECORDED)).toBeInTheDocument();
    expect(screen.queryByText("null")).not.toBeInTheDocument();
  });

  // --- Redesign UI-6b: header, badges, the side panel --------------------------------

  it("has the page header, and colours each action's badge by kind with its label", async () => {
    mockedFetchAuditLogs.mockResolvedValueOnce(
      page([
        makeLog({ id: 1, action: "create" }),
        makeLog({ id: 2, action: "update" }),
        makeLog({ id: 3, action: "archive" }),
        makeLog({ id: 4, action: "bulk_import" }),
        RUNTIME_ERROR,
      ]),
    );
    render(<AdminAuditLogPage />);

    expect(screen.getByRole("heading", { level: 1, name: "Audit log" })).toBeInTheDocument();
    expect(screen.getByText("Every admin change and system error, append-only.")).toBeInTheDocument();
    await screen.findByText("Error");
    expect(badgeWithText("Create")).toHaveAttribute("data-tone", "positive");
    expect(badgeWithText("Update")).toHaveAttribute("data-tone", "neutral");
    expect(badgeWithText("Bulk Import")).toHaveAttribute("data-tone", "neutral");
    expect(screen.getByText("Error")).toHaveAttribute("data-tone", "danger");
    expect(badgeWithText("Archive")).toHaveAttribute("data-tone", "warning");
    expect(screen.queryByText("bulk_import")).not.toBeInTheDocument();
  });

  it("opens a row in a side panel with a readable before / after list and the raw data folded", async () => {
    mockedFetchAuditLogs.mockResolvedValueOnce(page([makeLog()]));
    const user = userEvent.setup();
    render(<AdminAuditLogPage />);

    const trigger = await screen.findByRole("button", { name: /2026/ });
    await user.click(trigger);

    const panel = screen.getByRole("dialog", { name: "Audit entry" });
    const before = within(panel).getByRole("heading", { name: "Before" }).parentElement as HTMLElement;
    expect(within(before).getByText("Rate percent")).toBeInTheDocument();
    // FX-3 (X13): formatted like the policy page (was the raw "3.0000" / "3.5000").
    expect(within(before).getByText("3.00%")).toBeInTheDocument();
    const after = within(panel).getByRole("heading", { name: "After" }).parentElement as HTMLElement;
    expect(within(after).getByText("3.50%")).toBeInTheDocument();
    expect(within(panel).getByText(/"rate_percent": "3.0000"/).closest("details")?.querySelector("summary")).toHaveTextContent(
      "Raw data",
    );
  });

  it("closes the panel on Escape and on Close, returning focus to the row", async () => {
    mockedFetchAuditLogs.mockResolvedValueOnce(page([makeLog()]));
    const user = userEvent.setup();
    render(<AdminAuditLogPage />);

    const trigger = await screen.findByRole("button", { name: /2026/ });
    await user.click(trigger);
    expect(screen.getByRole("dialog", { name: "Audit entry" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();

    await user.click(trigger);
    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("hints the resource types seen in the loaded rows, still free text", async () => {
    mockedFetchAuditLogs.mockResolvedValueOnce(page([makeLog(), RUNTIME_ERROR]));
    const { container } = render(<AdminAuditLogPage />);
    await screen.findByText("System error");

    const input = screen.getByLabelText("Resource type");
    expect(input).toHaveAttribute("list", "audit-resource-types");
    const options = Array.from(container.querySelectorAll("#audit-resource-types option")).map((o) => o.getAttribute("value"));
    expect(options).toEqual(["policy.InterestRate", "system.error"]);
  });

  it("offers Try again when the query fails, and it runs the same query again", async () => {
    mockedFetchAuditLogs.mockRejectedValueOnce(new Error("Network Error")).mockResolvedValueOnce(page([makeLog()]));
    const user = userEvent.setup();
    render(<AdminAuditLogPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load audit log entries. Please try again.");
    await user.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByText("admin@example.com")).toBeInTheDocument();
    expect(mockedFetchAuditLogs).toHaveBeenLastCalledWith(expect.objectContaining({ actor_email: "" }), 1);
  });
});
