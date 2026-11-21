import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";
import type { Location } from "react-router-dom";
import { LoginForm } from "../components/auth/LoginForm";
import { AuthLayout } from "../components/auth/AuthLayout";
import { useAuth } from "../context/AuthContext";
import { useDocumentTitle } from "../hooks/useDocumentTitle";

interface LocationState {
  from?: Location;
  justRegistered?: boolean;
}

export function LoginPage() {
  useDocumentTitle("Sign In");
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated } = useAuth();

  // QA audit L15: an already-signed-in user hitting /login directly
  // (back button, a stale bookmark) should land back in the app, not see
  // the sign-in form again.
  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  const state = location.state as LocationState | null;
  const from = state?.from;
  const redirectTo = from ? `${from.pathname}${from.search}${from.hash}` : "/";

  return (
    <AuthLayout>
      <h1 className="text-h2 font-semibold text-ink">Sign in to FlexiDriveMy</h1>
      {state?.justRegistered && (
        <p role="status" className="mt-4 rounded-md border border-positive-200 bg-positive-50 p-3 text-small text-positive-700">
          Account created - please sign in.
        </p>
      )}
      <div className="mt-6">
        <LoginForm onSuccess={() => navigate(redirectTo, { replace: true })} />
      </div>
      <p className="mt-4 text-small text-ink-muted">
        No account?{" "}
        <Link className="text-primary-700 underline" to="/register">
          Register
        </Link>
      </p>
    </AuthLayout>
  );
}
