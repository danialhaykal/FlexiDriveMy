import { Route, Routes } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import { ErrorBoundary } from "./components/common/ErrorBoundary";
import { ProtectedRoute } from "./components/common/ProtectedRoute";
import { AppShell } from "./components/layout/AppShell";
import { LoginPage } from "./pages/LoginPage";
import { RegisterPage } from "./pages/RegisterPage";
import { ProfilePage } from "./pages/ProfilePage";
import { DashboardPage } from "./pages/DashboardPage";
import { CatalogPage } from "./pages/CatalogPage";
import { VehicleDetailPage } from "./pages/VehicleDetailPage";
import { ComparisonPage } from "./pages/ComparisonPage";
import { ArenaPage } from "./pages/ArenaPage";
import { ScenariosPage } from "./pages/ScenariosPage";
import { SavedScenarioPage } from "./pages/SavedScenarioPage";
import { MlModelHistoryPage } from "./pages/MlModelHistoryPage";
import { AdminFleetPage } from "./pages/AdminFleetPage";
import { AdminPolicyPage } from "./pages/AdminPolicyPage";
import { AdminAuditLogPage } from "./pages/AdminAuditLogPage";
import { VehicleReadinessPage } from "./pages/VehicleReadinessPage";
import { FinancialProfilePage } from "./pages/FinancialProfilePage";
import { CreditsPage } from "./pages/CreditsPage";
import { NotFoundPage } from "./pages/NotFoundPage";

function App() {
  return (
    <ErrorBoundary>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />

          {/* Layout route: everything below renders inside AppShell's
              <Outlet />, behind a single ProtectedRoute check for the
              whole group rather than wrapping each page individually. */}
          <Route
            element={
              <ProtectedRoute>
                <AppShell />
              </ProtectedRoute>
            }
          >
            <Route path="/" element={<DashboardPage />} />
            <Route path="/profile" element={<ProfilePage />} />
            <Route path="/profile/financial" element={<FinancialProfilePage />} />
            <Route path="/catalog" element={<CatalogPage />} />
            <Route path="/catalog/:id" element={<VehicleDetailPage />} />
            <Route path="/catalog/:id/compare" element={<ComparisonPage />} />
            <Route path="/arena" element={<ArenaPage />} />
            <Route path="/scenarios" element={<ScenariosPage />} />
            <Route path="/scenarios/:id" element={<SavedScenarioPage />} />
            <Route path="/credits" element={<CreditsPage />} />
            <Route
              path="/admin/ml-model-history"
              element={
                <ProtectedRoute requireRole="admin">
                  <MlModelHistoryPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin/fleet"
              element={
                <ProtectedRoute requireRole="admin">
                  <AdminFleetPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin/policy"
              element={
                <ProtectedRoute requireRole="admin">
                  <AdminPolicyPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin/vehicle-readiness"
              element={
                <ProtectedRoute requireRole="admin">
                  <VehicleReadinessPage />
                </ProtectedRoute>
              }
            />
            <Route
              path="/admin/audit-log"
              element={
                <ProtectedRoute requireRole="admin">
                  <AdminAuditLogPage />
                </ProtectedRoute>
              }
            />
            {/* FX-2 (item 9): any other /admin/ address - a buyer is sent to the
                dashboard with "That page is for administrators.", an admin sees
                "Page not found". */}
            <Route
              path="/admin/*"
              element={
                <ProtectedRoute requireRole="admin">
                  <NotFoundPage />
                </ProtectedRoute>
              }
            />
            {/* FX-2 (item 9): an unknown address shows "Page not found" (it used to
                redirect to the dashboard without a word). Signed-out visitors still
                go to sign-in first, through the layout's ProtectedRoute. */}
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Routes>
      </AuthProvider>
    </ErrorBoundary>
  );
}

export default App;
