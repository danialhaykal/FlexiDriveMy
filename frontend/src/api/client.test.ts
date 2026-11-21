import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// QA audit H5: tests the response interceptor's actual refresh-on-401
// logic. axios itself is mocked (not the api/* wrapper functions, as
// other tests in this project do) because the thing under test IS the
// interceptor axios.create() registers - there's nothing to exercise
// without a real axios.create()/interceptors.response.use() call.
const mocks = vi.hoisted(() => {
  const requestUse = vi.fn();
  const responseUse = vi.fn();
  const instance = Object.assign(vi.fn(() => Promise.resolve({ data: "retried" })), {
    interceptors: { request: { use: requestUse }, response: { use: responseUse } },
  });
  const create = vi.fn(() => instance);
  const post = vi.fn();
  return { requestUse, responseUse, instance, create, post };
});

vi.mock("axios", () => ({
  default: {
    create: mocks.create,
    post: mocks.post,
    isAxiosError: (err: unknown): boolean =>
      Boolean(err && typeof err === "object" && "isAxiosError" in err),
  },
}));

function axiosError(status: number, url: string, extra: Record<string, unknown> = {}) {
  return {
    isAxiosError: true,
    response: { status },
    config: { url, ...extra },
  };
}

describe("apiClient response interceptor (QA audit H5)", () => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let onRejected: (error: any) => Promise<unknown>;
  let getAccessToken: () => string | null;
  let setAccessToken: (token: string | null) => void;

  beforeEach(async () => {
    localStorage.clear();
    mocks.responseUse.mockClear();
    mocks.post.mockClear();
    mocks.instance.mockClear();
    vi.resetModules();

    const client = await import("./client");
    onRejected = mocks.responseUse.mock.calls[0][1];
    getAccessToken = client.getAccessToken;
    setAccessToken = client.setAccessToken;
  });

  it("retries the original request with a new access token after a successful refresh", async () => {
    localStorage.setItem("flexidrive_refresh_token", "old-refresh");
    mocks.post.mockResolvedValueOnce({ data: { access: "new-access", refresh: "new-refresh" } });

    const error = axiosError(401, "/comparisons/");
    await onRejected(error);

    expect(mocks.post).toHaveBeenCalledWith(
      expect.stringContaining("/auth/login/refresh/"),
      { refresh: "old-refresh" },
    );
    // QA audit M22: the access token is never written to localStorage -
    // kept in memory only - while the rotated refresh token (server's
    // ROTATE_REFRESH_TOKENS=True) still is.
    expect(getAccessToken()).toBe("new-access");
    expect(localStorage.getItem("flexidrive_access_token")).toBeNull();
    expect(localStorage.getItem("flexidrive_refresh_token")).toBe("new-refresh");
    expect(mocks.instance).toHaveBeenCalledWith(
      expect.objectContaining({ url: "/comparisons/", _retriedAfterRefresh: true }),
    );
  });

  it("dedupes concurrent 401s into a single refresh call", async () => {
    localStorage.setItem("flexidrive_refresh_token", "old-refresh");
    mocks.post.mockResolvedValueOnce({ data: { access: "new-access" } });

    await Promise.all([
      onRejected(axiosError(401, "/comparisons/")),
      onRejected(axiosError(401, "/depreciation/tco/")),
    ]);

    expect(mocks.post).toHaveBeenCalledTimes(1);
  });

  it("clears the in-memory access token and stored refresh token, and calls the session-expired handler, when refresh itself fails", async () => {
    setAccessToken("stale-access");
    localStorage.setItem("flexidrive_refresh_token", "expired-refresh");
    mocks.post.mockRejectedValueOnce(axiosError(401, "/auth/login/refresh/"));

    const { setSessionExpiredHandler } = await import("./client");
    const handler = vi.fn();
    setSessionExpiredHandler(handler);

    const error = axiosError(401, "/comparisons/");
    await expect(onRejected(error)).rejects.toBe(error);

    expect(getAccessToken()).toBeNull();
    expect(localStorage.getItem("flexidrive_refresh_token")).toBeNull();
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("never re-triggers a refresh when the refresh endpoint itself 401s (no infinite loop)", async () => {
    const { setSessionExpiredHandler } = await import("./client");
    const handler = vi.fn();
    setSessionExpiredHandler(handler);

    const error = axiosError(401, "/auth/login/refresh/");
    await expect(onRejected(error)).rejects.toBe(error);

    expect(mocks.post).not.toHaveBeenCalled();
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("does not retry a request a second time after it was already retried once", async () => {
    const error = axiosError(401, "/comparisons/", { _retriedAfterRefresh: true });

    await expect(onRejected(error)).rejects.toBe(error);

    expect(mocks.post).not.toHaveBeenCalled();
    expect(mocks.instance).not.toHaveBeenCalled();
  });

  it("passes through a non-401 error untouched", async () => {
    const error = axiosError(500, "/comparisons/");

    await expect(onRejected(error)).rejects.toBe(error);

    expect(mocks.post).not.toHaveBeenCalled();
  });

  // --- QA audit M22 -------------------------------------------------------

  it("never writes the access token to localStorage, under any key", async () => {
    setAccessToken("some-access-token");

    expect(localStorage.length).toBe(0);
  });

  it("exports refreshAccessToken directly, usable outside a 401 (e.g. on page load)", async () => {
    localStorage.setItem("flexidrive_refresh_token", "old-refresh");
    mocks.post.mockResolvedValueOnce({ data: { access: "fresh-access" } });

    const { refreshAccessToken } = await import("./client");
    const result = await refreshAccessToken();

    expect(result).toBe("fresh-access");
    expect(getAccessToken()).toBe("fresh-access");
  });
});

// --- FX-1 (X2, Run 4 R4-K1): refreshes across tabs ------------------------------------------------------------------
// Two "tabs" are two separate imports of this module (each with its own in-page dedupe) sharing one localStorage and one
// lock manager, against a fake server that rotates and blacklists exactly like ROTATE_REFRESH_TOKENS /
// BLACKLIST_AFTER_ROTATION: only the latest refresh token works, and each successful refresh replaces it.
describe("refresh across tabs (FX-1 X2)", () => {
  type Client = typeof import("./client");
  let validRefresh: string;
  let issued: number;

  function installFakeLocks() {
    let chain: Promise<unknown> = Promise.resolve();
    const locks = {
      request: vi.fn((_name: string, _options: unknown, callback: () => Promise<unknown>) => {
        const run = chain.then(() => callback());
        chain = run.catch(() => undefined);
        return run;
      }),
    };
    Object.defineProperty(navigator, "locks", { value: locks, configurable: true });
    return locks;
  }

  function rotatingServer() {
    mocks.post.mockImplementation(async (_url: string, body: { refresh: string }) => {
      await new Promise((resolve) => setTimeout(resolve, 5)); // a real round trip, so calls can overlap
      if (body.refresh !== validRefresh) throw axiosError(401, "/auth/login/refresh/");
      issued += 1;
      validRefresh = `refresh-${issued}`;
      return { data: { access: `access-${issued}`, refresh: validRefresh } };
    });
  }

  async function openTab(): Promise<Client> {
    vi.resetModules();
    return import("./client");
  }

  beforeEach(() => {
    localStorage.clear();
    mocks.post.mockReset();
    validRefresh = "refresh-0";
    issued = 0;
    localStorage.setItem("flexidrive_refresh_token", "refresh-0");
  });

  afterEach(() => {
    // jsdom has no Web Locks; leave it that way for the other suites.
    delete (navigator as unknown as Record<string, unknown>).locks;
  });

  it("two tabs refreshing at the same moment both stay signed in (the second waits, then uses the rotated token)", async () => {
    const locks = installFakeLocks();
    rotatingServer();
    const tabA = await openTab();
    const tabB = await openTab();

    const [a, b] = await Promise.all([tabA.refreshAccessToken(), tabB.refreshAccessToken()]);

    expect(locks.request).toHaveBeenCalledWith("fdm-token-refresh", { mode: "exclusive" }, expect.any(Function));
    expect([a, b].sort()).toEqual(["access-1", "access-2"]);
    expect(mocks.post.mock.calls.map(([, body]) => body.refresh)).toEqual(["refresh-0", "refresh-1"]);
    expect(localStorage.getItem("flexidrive_refresh_token")).toBe("refresh-2");
  });

  it("a stale-token 401 after another tab rotated does not clear storage (retried once with the new token)", async () => {
    // No lock (the in-page fallback): tab A sends refresh-0, tab B has rotated it to refresh-1 before A's 401 arrives.
    mocks.post
      .mockImplementationOnce(async () => {
        localStorage.setItem("flexidrive_refresh_token", "refresh-1"); // tab B's rotation lands first
        throw axiosError(401, "/auth/login/refresh/");
      })
      .mockResolvedValueOnce({ data: { access: "access-2", refresh: "refresh-2" } });
    const tabA = await openTab();
    const handler = vi.fn();
    tabA.setSessionExpiredHandler(handler);
    const onRejectedA = mocks.responseUse.mock.calls.at(-1)![1];

    await expect(onRejectedA(axiosError(401, "/comparisons/"))).resolves.toBeDefined();

    expect(mocks.post.mock.calls.map(([, body]) => body.refresh)).toEqual(["refresh-0", "refresh-1"]);
    expect(localStorage.getItem("flexidrive_refresh_token")).toBe("refresh-2");
    expect(handler).not.toHaveBeenCalled();
  });

  it("keeps the stored token when even the retry is answered for a token another tab has replaced again", async () => {
    mocks.post
      .mockImplementationOnce(async () => {
        localStorage.setItem("flexidrive_refresh_token", "refresh-1");
        throw axiosError(401, "/auth/login/refresh/");
      })
      .mockImplementationOnce(async () => {
        localStorage.setItem("flexidrive_refresh_token", "refresh-2");
        throw axiosError(401, "/auth/login/refresh/");
      });
    const tabA = await openTab();
    const handler = vi.fn();
    tabA.setSessionExpiredHandler(handler);
    const onRejectedA = mocks.responseUse.mock.calls.at(-1)![1];

    const original = axiosError(401, "/comparisons/");
    await expect(onRejectedA(original)).rejects.toBe(original);

    expect(localStorage.getItem("flexidrive_refresh_token")).toBe("refresh-2"); // the other tab's working token
    expect(handler).not.toHaveBeenCalled();
  });

  it("a genuinely expired refresh token still signs out", async () => {
    installFakeLocks();
    validRefresh = "something-else"; // the stored refresh-0 is rejected and nobody replaces it
    rotatingServer();
    const tab = await openTab();
    const handler = vi.fn();
    tab.setSessionExpiredHandler(handler);
    const onRejected = mocks.responseUse.mock.calls.at(-1)![1];

    const original = axiosError(401, "/comparisons/");
    await expect(onRejected(original)).rejects.toBe(original);

    expect(localStorage.getItem("flexidrive_refresh_token")).toBeNull();
    expect(tab.getAccessToken()).toBeNull();
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("a logout in another tab signs this one out on its next refresh", async () => {
    installFakeLocks();
    rotatingServer();
    const tab = await openTab();
    const handler = vi.fn();
    tab.setSessionExpiredHandler(handler);
    const onRejected = mocks.responseUse.mock.calls.at(-1)![1];
    localStorage.removeItem("flexidrive_refresh_token"); // the other tab logged out

    const original = axiosError(401, "/comparisons/");
    await expect(onRejected(original)).rejects.toBe(original);

    expect(mocks.post).not.toHaveBeenCalled();
    expect(handler).toHaveBeenCalledTimes(1);
  });
});

// --- FX-1 X2b: the access token per tab in sessionStorage -------------------------------------------------------------
describe("access token kept per tab in sessionStorage (FX-1 X2b)", () => {
  function jwt(expSecondsFromNow: number): string {
    const payload = btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + expSecondsFromNow }))
      .replace(/=+$/, "")
      .replace(/\+/g, "-")
      .replace(/\//g, "_");
    return `h.${payload}.s`;
  }

  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    mocks.post.mockReset();
  });

  it("setAccessToken stores { access, expiresAt } for this tab and null clears it", async () => {
    vi.resetModules();
    const client = await import("./client");
    const token = jwt(900);

    client.setAccessToken(token);
    const stored = JSON.parse(sessionStorage.getItem("flexidrive_access_token")!);
    expect(stored.access).toBe(token);
    expect(Math.abs(stored.expiresAt - (Date.now() + 900_000))).toBeLessThan(2_000);
    expect(localStorage.getItem("flexidrive_access_token")).toBeNull(); // never in localStorage

    client.setAccessToken(null);
    expect(sessionStorage.getItem("flexidrive_access_token")).toBeNull();
  });

  it("a reload restores a token with more than 30 s left, without any refresh request", async () => {
    vi.resetModules();
    const first = await import("./client");
    const token = jwt(600);
    first.setAccessToken(token);

    vi.resetModules(); // the reload: a fresh module, nothing in memory
    const reloaded = await import("./client");
    expect(reloaded.getAccessToken()).toBeNull();
    expect(reloaded.restoreAccessTokenFromSession()).toBe(token);
    expect(reloaded.getAccessToken()).toBe(token);
    expect(mocks.post).not.toHaveBeenCalled();
  });

  it("a token with 30 s or less left is dropped, and the refresh that follows is one request", async () => {
    vi.resetModules();
    const first = await import("./client");
    first.setAccessToken(jwt(25));
    localStorage.setItem("flexidrive_refresh_token", "refresh-0");
    mocks.post.mockResolvedValueOnce({ data: { access: jwt(900), refresh: "refresh-1" } });

    vi.resetModules();
    const reloaded = await import("./client");
    expect(reloaded.restoreAccessTokenFromSession()).toBeNull();
    expect(sessionStorage.getItem("flexidrive_access_token")).toBeNull();
    await reloaded.refreshAccessToken();
    expect(mocks.post).toHaveBeenCalledTimes(1);
  });

  it("a failed refresh that signs out clears the stored access token", async () => {
    vi.resetModules();
    const client = await import("./client");
    client.setAccessToken(jwt(600));
    localStorage.setItem("flexidrive_refresh_token", "expired-refresh");
    mocks.post.mockRejectedValueOnce(axiosError(401, "/auth/login/refresh/"));
    const onRejected = mocks.responseUse.mock.calls.at(-1)![1];

    const original = axiosError(401, "/comparisons/");
    await expect(onRejected(original)).rejects.toBe(original);

    expect(sessionStorage.getItem("flexidrive_access_token")).toBeNull();
  });
});
