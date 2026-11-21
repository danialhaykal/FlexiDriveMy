import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import type { UserRole } from "../../types/auth";
import { ADMIN_ONLY_NOTICE } from "../../lib/notices";

interface ProtectedRouteProps {
  children: ReactNode;
  requireRole?: UserRole;
}

export function ProtectedRoute({ children, requireRole }: ProtectedRouteProps) {
  const { user, isAuthenticated, isLoading } = useAuth();
  const location = useLocation();

  if (isLoading) {
    return <p className="p-6 text-slate-500">Loading…</p>;
  }

  if (!isAuthenticated) {
    // QA audit L15: carry the page the user actually asked for, so
    // LoginPage can send them back there instead of always "/".
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  if (requireRole && user?.role !== requireRole) {
    // FX-2 (item 9, R4-F30f): the dashboard says why ("That page is for administrators.").
    return <Navigate to="/" replace state={{ notice: ADMIN_ONLY_NOTICE }} />;
  }

  return <>{children}</>;
}
