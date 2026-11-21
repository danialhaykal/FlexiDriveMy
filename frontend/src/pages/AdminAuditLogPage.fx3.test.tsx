import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AdminAuditLogPage } from "./AdminAuditLogPage";
import { fetchAuditLogs } from "../api/audit";
import type { AuditLog } from "../types/audit";
import { auditResourceName, changedAuditKeys, formatAuditValue } from "../lib/auditDisplay";

// FX-3 (X13): readable resource names (raw type kept in Raw data), values formatted like the policy page, and the
// fields that changed highlighted in the drawer.

vi.mock("../api/audit", () => ({ fetchAuditLogs: vi.fn() }));
const mockedFetchAuditLogs = vi.mocked(fetchAuditLogs);

function makeLog(overrides: Partial<AuditLog> = {}): AuditLog {
  return {
    id: 1, actor_id: 7, actor_email: "admin@example.com", timestamp: "2026-10-30T06:18:00Z", action: "update",
    resource_type: "policy.InterestRate", resource_id: "4", ip_address: "127.0.0.1",
    before_data: { id: 4, brand_name: "BMW", rate_percent: "2.5000", is_active: true },
    after_data: { id: 4, brand_name: "BMW", rate_percent: "2.8000", is_active: true },
    ...overrides,
  };
}

describe("audit display helpers", () => {
  it("names resources in words", () => {
    expect(auditResourceName("policy.InterestRate", "4")).toBe("Interest rate #4");
    expect(auditResourceName("vehicles.VehicleModel", "25")).toBe("Vehicle #25");
    expect(auditResourceName("system.error", "pdf_export")).toBe("System error");
    expect(auditResourceName("policy.SomeNewThing", "2")).toBe("Some new thing #2");
  });

  it("formats values like the policy page", () => {
    expect(formatAuditValue("rate_percent", "2.8000")).toBe("2.80%");
    expect(formatAuditValue("residual_value_ratio", "0.7807")).toBe("78.07%");
    expect(formatAuditValue("delta_points", "0.0600")).toBe("+6.00 pts");
    expect(formatAuditValue("msrp", "265800.00")).toBe("RM 265,800.00");
    expect(formatAuditValue("maintenance_cap_annual", "8000.00")).toBe("RM 8,000.00");
    expect(formatAuditValue("effective_from", "2026-01-01")).toBe("1 Jan 2026");
    expect(formatAuditValue("is_active", false)).toBe("No");
    expect(formatAuditValue("tenure_months", 36)).toBe("36");
    expect(formatAuditValue("low_km_cap", 10000)).toBe("10,000");
    expect(formatAuditValue("brand_name", "BMW")).toBe("BMW");
    expect(formatAuditValue("model_year", null)).toBe("—");
  });

  it("lists only keys whose value changed, and nothing for a one-sided row", () => {
    expect([...changedAuditKeys({ a: 1, b: "x" }, { a: 2, b: "x", c: true })]).toEqual(["a", "c"]);
    expect(changedAuditKeys(null, { a: 1 }).size).toBe(0);
  });
});

describe("AdminAuditLogPage FX-3", () => {
  beforeEach(() => mockedFetchAuditLogs.mockReset());

  it("shows the readable resource name in the row and drawer, the raw type under Raw data", async () => {
    mockedFetchAuditLogs.mockResolvedValueOnce({ count: 1, next: null, previous: null, results: [makeLog()] });
    const user = userEvent.setup();
    render(<AdminAuditLogPage />);

    expect(await screen.findByText("Interest rate #4")).toBeInTheDocument();
    expect(screen.queryByText(/policy\.InterestRate #4/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /30 Oct 2026, \d{1,2}:18 (am|pm)/ }));

    const panel = screen.getByRole("dialog", { name: "Audit entry" });
    expect(within(panel).getByText(/Interest rate #4/)).toBeInTheDocument();
    const raw = within(panel).getByText("Raw data").closest("details") as HTMLElement;
    expect(within(raw).getByText("policy.InterestRate")).toBeInTheDocument();
  });

  it("highlights only the changed field, on both sides, with formatted values", async () => {
    mockedFetchAuditLogs.mockResolvedValueOnce({ count: 1, next: null, previous: null, results: [makeLog()] });
    const user = userEvent.setup();
    render(<AdminAuditLogPage />);
    await user.click(await screen.findByRole("button", { name: /30 Oct 2026/ }));

    const panel = screen.getByRole("dialog", { name: "Audit entry" });
    const before = within(panel).getByRole("heading", { name: "Before" }).parentElement as HTMLElement;
    const after = within(panel).getByRole("heading", { name: "After" }).parentElement as HTMLElement;
    for (const [side, value] of [[before, "2.50%"], [after, "2.80%"]] as const) {
      const changedRows = side.querySelectorAll('[data-changed="true"]');
      expect(changedRows).toHaveLength(1);
      expect(changedRows[0]).toHaveTextContent(`Rate percentChanged${value}`);
      expect(within(side).getByText("BMW").closest("div")).not.toHaveAttribute("data-changed");
    }
  });

  it("highlights nothing on a create", async () => {
    mockedFetchAuditLogs.mockResolvedValueOnce({
      count: 1, next: null, previous: null, results: [makeLog({ action: "create", before_data: null })],
    });
    const user = userEvent.setup();
    render(<AdminAuditLogPage />);
    await user.click(await screen.findByRole("button", { name: /30 Oct 2026/ }));

    expect(screen.getByRole("dialog").querySelectorAll('[data-changed="true"]')).toHaveLength(0);
  });
});
