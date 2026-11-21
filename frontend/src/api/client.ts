import axios from "axios";
import type { AxiosRequestConfig } from "axios";

// QA audit M22, explicit scope-down judgment call: the FULL fix (httpOnly
// cookies for the refresh token) needs the backend to set/read a cookie
// instead of the client managing a token string at all, plus CORS/CSRF
// changes and LoginView/LogoutView/refresh-endpoint rework - a real
// architecture change, out of proportion to one batch. This instead
// shrinks the XSS blast radius without any backend change: the ACCESS
// token (short-lived, 15 minutes) is kept in memory only - a page
// reload always loses it, by design (FX-1 X2b reverses this: it is now also
// kept per tab in sessionStorage - see ACCESS_TOKEN_SESSION_KEY below), same as it would with an httpOnly
// cookie an XSS payload can't read either - never written to
// localStorage at all. The REFRESH token (longer-lived, 7 days) still
// lives in localStorage, since replacing that one too is the full
// migration being deliberately deferred - flagged here as a named
// follow-up, same as H11 flagged the ML Model Management admin page
// rather than silently leaving M22 half-done and calling it closed.
export const REFRESH_TOKEN_KEY = "flexidrive_refresh_token";

let accessToken: string | null = null;

// FX-1 X2b: the access token is ALSO kept per tab in sessionStorage
// ({ access, expiresAt }), so a reload in the same tab does not need a
// refresh while it is still valid. Without it, a reload while a refresh was
// in flight lost the rotated refresh token (the server had already
// blacklisted the old one; the dying page never saved the new one) and
// signed the buyer out. This reverses QA audit M22's "access token in
// memory only" (see above): sessionStorage is readable by an XSS payload,
// but so is the 7-day refresh token already in localStorage, and this
// 15-minute token is per tab and gone when the tab closes. The in-memory
// copy stays the working value; sessionStorage is only read at start-up.
export const ACCESS_TOKEN_SESSION_KEY = "flexidrive_access_token";
// A stored token with less than this left is refreshed instead of reused.
const MIN_REMAINING_MS = 30_000;

function tokenExpiresAt(token: string): number | null {
  try {
    const payload = token.split(".")[1];
    const json = JSON.parse(atob(payload.replace(/-/g, "+").replace(/_/g, "/")));
    return typeof json.exp === "number" ? json.exp * 1000 : null;
  } catch {
    return null;
  }
}

function writeSessionAccessToken(token: string | null): void {
  try {
    const expiresAt = token ? tokenExpiresAt(token) : null;
    if (token && expiresAt !== null) {
      sessionStorage.setItem(ACCESS_TOKEN_SESSION_KEY, JSON.stringify({ access: token, expiresAt }));
    } else {
      sessionStorage.removeItem(ACCESS_TOKEN_SESSION_KEY);
    }
  } catch {
    // Storage unavailable (private mode, quota): the in-memory token still works.
  }
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
  writeSessionAccessToken(token);
}

// Start-up: this tab's stored access token, if it has more than 30 s left
// (it becomes the in-memory token); otherwise it is removed and null is
// returned, and the caller refreshes through the locked refresh.
export function restoreAccessTokenFromSession(now: number = Date.now()): string | null {
  try {
    const raw = sessionStorage.getItem(ACCESS_TOKEN_SESSION_KEY);
    if (!raw) return null;
    const { access, expiresAt } = JSON.parse(raw) as { access?: unknown; expiresAt?: unknown };
    if (typeof access === "string" && typeof expiresAt === "number" && expiresAt - now > MIN_REMAINING_MS) {
      accessToken = access;
      return access;
    }
    sessionStorage.removeItem(ACCESS_TOKEN_SESSION_KEY);
  } catch {
    // unreadable entry: fall through to a refresh
  }
  return null;
}

const API_BASE_URL =
  (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000/api";

const REFRESH_PATH = "/auth/login/refresh/";

export const apiClient = axios.create({ baseURL: API_BASE_URL });

apiClient.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// QA audit H5: the access token's 15-minute lifetime previously had no
// refresh plumbing at all - every call just 401'd once it expired, and
// each panel showed its own generic "unavailable" message with no way to
// recover short of a manual page reload (which only works because
// AuthContext's own profile fetch happens to also go through this same
// 401 handling now).
//
// Reactive refresh-on-401 (not a proactive timer): simpler, and
// sufficient given ACCESS_TOKEN_LIFETIME is 15 minutes - a background
// timer would need its own drift/cleanup handling for a problem a
// request-time check already solves transparently, and the cost of
// "reactive" here is just one extra round trip on the rare request that
// straddles the expiry boundary, not a visible delay.
let sessionExpiredHandler: (() => void) | null = null;

export function setSessionExpiredHandler(handler: (() => void) | null): void {
  sessionExpiredHandler = handler;
}

// Concurrent 401s (e.g. two panels' requests landing after expiry at
// roughly the same time) must trigger exactly ONE refresh call, not one
// per failed request - every caller awaits the same in-flight promise.
// Exported (not just used internally) so AuthContext's own mount effect
// can proactively exchange a stored refresh token for a fresh in-memory
// access token - the only way to recover a session after a reload, now
// that the access token itself is never persisted.
let refreshPromise: Promise<string> | null = null;

// FX-1 (X2, Run 4 R4-K1): the in-page dedupe above covers ONE page. Two tabs
// (or a reload while a page is still starting) each refreshed with the same
// stored refresh token; the server rotates and blacklists on every refresh
// (ROTATE_REFRESH_TOKENS / BLACKLIST_AFTER_ROTATION, kept as they are), so the
// second one got a 401 and that tab's handler cleared the SHARED stored token,
// signing every tab out. Now:
//   1. refreshes are serialised across tabs and page loads with the Web Locks
//      API (the in-page dedupe stays where navigator.locks is missing);
//   2. inside the lock the refresh token is read from storage again - another
//      tab may have rotated it while this one waited;
//   3. a 401 whose token has since been replaced in storage is retried once
//      with the new token, and a refresh failure clears the session only if
//      the stored token is still the one that failed (see
//      shouldEndSessionAfterRefreshError).
// A real logout still reaches every tab: the server blacklists that tab's
// tokens and removes the stored one, so another tab's next refresh finds no
// token (or a rejected one that is still stored) and signs out.
export const REFRESH_LOCK_NAME = "fdm-token-refresh";

export async function refreshAccessToken(): Promise<string> {
  if (!refreshPromise) {
    refreshPromise = withRefreshLock(performTokenRefresh).finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

function withRefreshLock<T>(task: () => Promise<T>): Promise<T> {
  const locks = typeof navigator !== "undefined" ? navigator.locks : undefined;
  if (!locks || typeof locks.request !== "function") return task();
  return locks.request(REFRESH_LOCK_NAME, { mode: "exclusive" }, () => task());
}

// The refresh token a refresh call was made with, kept on the error it threw,
// so a caller can tell a token that is really dead from one another tab has
// already rotated (and saved) in the meantime.
const FAILED_REFRESH_TOKEN = Symbol("failedRefreshToken");

function isUnauthorized(error: unknown): boolean {
  return axios.isAxiosError(error) && error.response?.status === 401;
}

async function exchangeRefreshToken(refreshToken: string): Promise<string> {
  // A plain axios call, never apiClient - going through apiClient would
  // re-enter this same response interceptor on a 401 from the refresh
  // endpoint itself (an expired/invalid refresh token), which is exactly
  // the infinite-loop case this must avoid.
  try {
    const { data } = await axios.post<{ access: string; refresh?: string }>(
      `${API_BASE_URL}${REFRESH_PATH}`,
      { refresh: refreshToken },
    );
    setAccessToken(data.access);
    if (data.refresh) {
      // SIMPLE_JWT's ROTATE_REFRESH_TOKENS=True (config/settings.py) means
      // the server blacklists the OLD refresh token the moment it issues
      // this new one - persisting it is not optional polish, the old
      // string genuinely stops working after this point.
      localStorage.setItem(REFRESH_TOKEN_KEY, data.refresh);
    }
    return data.access;
  } catch (error) {
    if (error && typeof error === "object") {
      (error as Record<symbol, unknown>)[FAILED_REFRESH_TOKEN] = refreshToken;
    }
    throw error;
  }
}

async function performTokenRefresh(): Promise<string> {
  // Read inside the lock: another tab may have rotated it while this one waited.
  const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
  if (!refreshToken) {
    throw new Error("No refresh token available.");
  }
  try {
    return await exchangeRefreshToken(refreshToken);
  } catch (error) {
    const current = localStorage.getItem(REFRESH_TOKEN_KEY);
    if (isUnauthorized(error) && current && current !== refreshToken) {
      // Rotated by another tab or page meanwhile: one retry with the new token.
      return exchangeRefreshToken(current);
    }
    throw error;
  }
}

// True when a refresh failure means this session is over. A 401 for a token
// that is no longer the stored one (another tab rotated it) is not: storage
// holds a newer, working token, and clearing it would sign every tab out.
export function shouldEndSessionAfterRefreshError(error: unknown): boolean {
  if (isUnauthorized(error) && error && typeof error === "object") {
    const failed = (error as Record<symbol, unknown>)[FAILED_REFRESH_TOKEN];
    const current = localStorage.getItem(REFRESH_TOKEN_KEY);
    if (typeof failed === "string" && current !== null && current !== failed) return false;
  }
  return true;
}

function clearSession(): void {
  setAccessToken(null);
  localStorage.removeItem(REFRESH_TOKEN_KEY);
}

interface RetryableRequestConfig extends AxiosRequestConfig {
  _retriedAfterRefresh?: boolean;
}

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    if (!axios.isAxiosError(error) || error.response?.status !== 401) {
      return Promise.reject(error);
    }

    const originalRequest = error.config as RetryableRequestConfig | undefined;
    const isRefreshCall = originalRequest?.url?.includes(REFRESH_PATH);

    // A 401 from the refresh call itself (expired/invalid refresh token)
    // must never re-trigger another refresh attempt - that's the
    // infinite-loop case. Same for a request already retried once: a
    // second 401 right after a successful refresh means the new access
    // token was rejected for some other reason, not that refreshing
    // again would help.
    if (!originalRequest || isRefreshCall || originalRequest._retriedAfterRefresh) {
      if (isRefreshCall) {
        clearSession();
        sessionExpiredHandler?.();
      }
      return Promise.reject(error);
    }

    originalRequest._retriedAfterRefresh = true;

    try {
      const newAccessToken = await refreshAccessToken();
      originalRequest.headers = {
        ...originalRequest.headers,
        Authorization: `Bearer ${newAccessToken}`,
      };
      return apiClient(originalRequest);
    } catch (refreshError) {
      if (shouldEndSessionAfterRefreshError(refreshError)) {
        clearSession();
        sessionExpiredHandler?.();
      }
      return Promise.reject(error);
    }
  },
);
