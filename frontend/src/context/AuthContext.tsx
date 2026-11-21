import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import axios from "axios";
import { useLocation, useNavigate } from "react-router-dom";
import { fetchProfileRequest, loginRequest, logoutRequest, updateProfileRequest } from "../api/auth";
import {
  REFRESH_TOKEN_KEY,
  refreshAccessToken,
  restoreAccessTokenFromSession,
  shouldEndSessionAfterRefreshError,
  setAccessToken,
  setSessionExpiredHandler,
} from "../api/client";
import type { AuthUser, ProfileUpdatePayload } from "../types/auth";

interface AuthContextValue {
  user: AuthUser | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  updateProfile: (payload: ProfileUpdatePayload) => Promise<AuthUser>;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    // QA audit M22: the access token is never persisted (in-memory only
    // - see api/client.ts), so a page reload always starts with none in
    // memory, by design - the stored REFRESH token is what's actually
    // checked here, exchanged up front for a fresh access token before
    // the profile fetch even runs, rather than relying on that first
    // request 401ing and triggering the interceptor's own reactive
    // refresh (which would work too, but means an extra round trip and a
    // flash of "logged out" on every single reload).
    const storedRefreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
    if (!storedRefreshToken) {
      setIsLoading(false);
      return;
    }
    // FX-1 X2b: a reload in this tab reuses its own access token while it has
    // more than 30 s left - no refresh, so no rotation to lose if the page is
    // reloaded again mid-request. Otherwise the locked refresh, as before.
    const start = restoreAccessTokenFromSession() ? Promise.resolve() : refreshAccessToken().then(() => undefined);
    start
      .then(() => fetchProfileRequest())
      .then(setUser)
      .catch((err: unknown) => {
        // QA audit L15: a transient network blip (no response at all, or
        // a 5xx) must not be treated the same as a real "this session is
        // invalid" - only an actual 401 (the refresh token itself is
        // expired/invalid) should wipe the stored refresh token. Anything
        // else leaves it in place so the next reload can simply try again.
        // FX-1 (X2): and only when the stored token is still the one that
        // was rejected - if another tab rotated it meanwhile, it is a newer,
        // working token and removing it would sign every tab out.
        if (axios.isAxiosError(err) && err.response?.status === 401 && shouldEndSessionAfterRefreshError(err)) {
          localStorage.removeItem(REFRESH_TOKEN_KEY);
          setAccessToken(null);
        }
      })
      .finally(() => setIsLoading(false));
  }, []);

  useEffect(() => {
    // FX-1 X2b: another tab removed the stored refresh token (a logout, or a
    // refresh that signed it out): drop this tab's access token too (memory and
    // sessionStorage), so its next request 401s, finds no refresh token and
    // signs this tab out through the session-expired handler.
    const onStorage = (event: StorageEvent) => {
      if ((event.key === REFRESH_TOKEN_KEY || event.key === null) && localStorage.getItem(REFRESH_TOKEN_KEY) === null) {
        setAccessToken(null);
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  useEffect(() => {
    // QA audit H5: apiClient's response interceptor calls this when a
    // request 401s and the refresh attempt ALSO fails (or there's no
    // refresh token at all) - the one place that actually knows how to
    // clear React's own user state and navigate, since api/client.ts is
    // plain axios setup with no React/router access of its own.
    setSessionExpiredHandler(() => {
      setUser(null);
      navigate("/login", { replace: true, state: { from: location } });
    });
    return () => setSessionExpiredHandler(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [navigate]);

  const login = useCallback(async (email: string, password: string) => {
    setError(null);
    try {
      const data = await loginRequest(email, password);
      setAccessToken(data.access);
      localStorage.setItem(REFRESH_TOKEN_KEY, data.refresh);
      setUser(data.user);
    } catch (err) {
      setError("Invalid email or password.");
      throw err;
    }
  }, []);

  const logout = useCallback(async () => {
    const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
    try {
      if (refreshToken) {
        await logoutRequest(refreshToken);
      }
    } finally {
      setAccessToken(null);
      localStorage.removeItem(REFRESH_TOKEN_KEY);
      setUser(null);
    }
  }, []);

  const updateProfile = useCallback(async (payload: ProfileUpdatePayload) => {
    const updated = await updateProfileRequest(payload);
    setUser(updated);
    return updated;
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      user,
      isAuthenticated: user !== null,
      isLoading,
      error,
      login,
      logout,
      updateProfile,
    }),
    [user, isLoading, error, login, logout, updateProfile],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
