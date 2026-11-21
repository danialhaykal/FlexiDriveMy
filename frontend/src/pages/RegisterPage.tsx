import { Link, Navigate, useNavigate } from "react-router-dom";
import { RegisterForm } from "../components/auth/RegisterForm";
import { useAuth } from "../context/AuthContext";
import { useDocumentTitle } from "../hooks/useDocumentTitle";
import { AuthLayout } from "../components/auth/AuthLayout";

export function RegisterPage() {
  useDocumentTitle("Create Account");
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();

  // Run 2 fix batch 3: a signed-in user opening /register (back button, a stale
  // bookmark) lands back in the app, exactly as /login does.
  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  return (
    <AuthLayout>
      <h1 className="text-h2 font-semibold text-ink">Create your account</h1>
      <div className="mt-6">
        <RegisterForm
          onSuccess={() =>
            // QA audit M20: UC001 asks for a visible success message,
            // not a silent redirect - LoginPage reads this via
            // location.state and shows a one-time confirmation banner.
            navigate("/login", { replace: true, state: { justRegistered: true } })
          }
        />
      </div>
      <p className="mt-4 text-small text-ink-muted">
        Already have an account?{" "}
        <Link className="text-primary-700 underline" to="/login">
          Sign in
        </Link>
      </p>
    </AuthLayout>
  );
}
