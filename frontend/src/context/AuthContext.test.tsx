import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider, useAuth } from "./AuthContext";
import { fetchProfileRequest, logoutRequest } from "../api/auth";
import { ACCESS_TOKEN_SESSION_KEY, REFRESH_TOKEN_KEY, getAccessToken, refreshAccessToken } from "../api/client";

// FX-1 X2b: the access token is kept per tab in sessionStorage so a reload does not need a refresh while it is valid.
// The real client module is used (restore / storage), with only refreshAccessToken replaced by a spy.
vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, refreshAccessToken: vi.fn() };
});
vi.mock("../api/auth", () => ({
  fetchProfileRequest: vi.fn(),
  loginRequest: vi.fn(),
  logoutRequest: vi.fn(),
  updateProfileRequest: vi.fn(),
}));

const mockedRefresh = vi.mocked(refreshAccessToken);
const mockedFetchProfile = vi.mocked(fetchProfileRequest);
const mockedLogout = vi.mocked(logoutRequest);

function jwt(expSecondsFromNow: number): string {
  const payload = btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + expSecondsFromNow, user_id: 8 }))
    .replace(/=+$/, "")
    .replace(/\+/g, "-")
    .replace(/\//g, "_");
  return `eyJhbGciOiJIUzI1NiJ9.${payload}.signature`;
}

function storeSessionAccess(token: string, expiresInMs: number) {
  sessionStorage.setItem(ACCESS_TOKEN_SESSION_KEY, JSON.stringify({ access: token, expiresAt: Date.now() + expiresInMs }));
}

function Probe() {
  const { user, isLoading, logout } = useAuth();
  if (isLoading) return <p>loading</p>;
  return (
    <div>
      <p>{user ? `signed in as ${user.email}` : "signed out"}</p>
      <button type="button" onClick={() => void logout()}>
        Logout
      </button>
    </div>
  );
}

function renderAuth() {
  return render(
    <MemoryRouter>
      <AuthProvider>
        <Probe />
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("AuthProvider session start-up (FX-1 X2b)", () => {
  beforeEach(() => {
    localStorage.clear();
    sessionStorage.clear();
    mockedRefresh.mockReset();
    mockedFetchProfile.mockReset();
    mockedLogout.mockReset();
    mockedFetchProfile.mockResolvedValue({ id: 8, email: "buyer@example.test" } as never);
    localStorage.setItem(REFRESH_TOKEN_KEY, "refresh-0");
  });

  afterEach(() => {
    sessionStorage.clear();
  });

  it("a reload with a valid stored access token makes no refresh request", async () => {
    const token = jwt(600);
    storeSessionAccess(token, 600_000);

    renderAuth();

    expect(await screen.findByText("signed in as buyer@example.test")).toBeInTheDocument();
    expect(mockedRefresh).not.toHaveBeenCalled();
    expect(getAccessToken()).toBe(token);
  });

  it("a stored access token with 30 s or less left triggers one refresh", async () => {
    storeSessionAccess(jwt(20), 20_000);
    mockedRefresh.mockResolvedValueOnce("fresh-access");

    renderAuth();

    expect(await screen.findByText("signed in as buyer@example.test")).toBeInTheDocument();
    expect(mockedRefresh).toHaveBeenCalledTimes(1);
    expect(sessionStorage.getItem(ACCESS_TOKEN_SESSION_KEY)).toBeNull(); // the too-short token was dropped
  });

  it("a new tab (nothing in sessionStorage) refreshes once", async () => {
    mockedRefresh.mockResolvedValueOnce("fresh-access");

    renderAuth();

    expect(await screen.findByText("signed in as buyer@example.test")).toBeInTheDocument();
    expect(mockedRefresh).toHaveBeenCalledTimes(1);
  });

  it("logout clears this tab's stored access token", async () => {
    storeSessionAccess(jwt(600), 600_000);
    mockedLogout.mockResolvedValueOnce(undefined);
    const user = userEvent.setup();

    renderAuth();
    await screen.findByText("signed in as buyer@example.test");
    await user.click(screen.getByRole("button", { name: "Logout" }));

    expect(await screen.findByText("signed out")).toBeInTheDocument();
    expect(sessionStorage.getItem(ACCESS_TOKEN_SESSION_KEY)).toBeNull();
    expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBeNull();
    expect(getAccessToken()).toBeNull();
  });

  it("another tab removing the refresh token drops this tab's access token, so its next request signs out", async () => {
    storeSessionAccess(jwt(600), 600_000);

    renderAuth();
    await screen.findByText("signed in as buyer@example.test");
    expect(getAccessToken()).not.toBeNull();

    // the other tab logged out: the shared refresh token is gone and the browser tells this tab
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    act(() => {
      window.dispatchEvent(new StorageEvent("storage", { key: REFRESH_TOKEN_KEY, oldValue: "refresh-0", newValue: null }));
    });

    // No access token is left, so the next API call 401s and the interceptor finds no refresh token to use - the
    // "a logout in another tab signs this one out on its next refresh" case in api/client.test.ts.
    expect(getAccessToken()).toBeNull();
    expect(sessionStorage.getItem(ACCESS_TOKEN_SESSION_KEY)).toBeNull();
  });

  it("another tab only rotating the refresh token leaves this tab's access token alone", async () => {
    const token = jwt(600);
    storeSessionAccess(token, 600_000);

    renderAuth();
    await screen.findByText("signed in as buyer@example.test");
    localStorage.setItem(REFRESH_TOKEN_KEY, "refresh-1");
    act(() => {
      window.dispatchEvent(new StorageEvent("storage", { key: REFRESH_TOKEN_KEY, oldValue: "refresh-0", newValue: "refresh-1" }));
    });

    expect(getAccessToken()).toBe(token);
  });
});
