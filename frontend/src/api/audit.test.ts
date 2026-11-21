import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchAuditLogs } from "./audit";
import { apiClient } from "./client";

vi.mock("./client", () => ({ apiClient: { get: vi.fn() } }));
const mockedGet = vi.mocked(apiClient.get);

describe("fetchAuditLogs query parameters", () => {
  beforeEach(() => {
    mockedGet.mockReset();
    mockedGet.mockResolvedValue({ data: { count: 0, next: null, previous: null, results: [] } });
  });

  it("sends the user email as actor_email (trimmed), alongside the page", async () => {
    await fetchAuditLogs({ actor_email: "  admin@example.com " }, 2);

    expect(mockedGet).toHaveBeenCalledWith("/audit/logs/", {
      params: { actor_email: "admin@example.com", page: 2 },
    });
  });

  it("still sends the id filter for callers that use it, and the two together", async () => {
    await fetchAuditLogs({ actor: "7" });
    await fetchAuditLogs({ actor: "7", actor_email: "admin@example.com", action: "update" });

    expect(mockedGet).toHaveBeenNthCalledWith(1, "/audit/logs/", { params: { actor: "7", page: 1 } });
    expect(mockedGet).toHaveBeenNthCalledWith(2, "/audit/logs/", {
      params: { actor: "7", actor_email: "admin@example.com", action: "update", page: 1 },
    });
  });

  it("sends nothing for an empty email", async () => {
    await fetchAuditLogs({ actor_email: "", action: "" });

    expect(mockedGet).toHaveBeenCalledWith("/audit/logs/", { params: { page: 1 } });
  });
});
