import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "../components/layout/AppShell";
import { isAuthenticated } from "../shared/auth";

// Lazy-loaded pages for code splitting
const LoginPage = lazy(() => import("../features/auth/LoginPage").then((m) => ({ default: m.LoginPage })));
const DashboardPage = lazy(() => import("../features/dashboard/DashboardPage").then((m) => ({ default: m.DashboardPage })));
const TaggerStatusPage = lazy(() => import("../features/tagger-status/TaggerStatusPage").then((m) => ({ default: m.TaggerStatusPage })));
const BrowsePage = lazy(() => import("../features/browse/BrowsePage").then((m) => ({ default: m.BrowsePage })));
const AnalyticsPage = lazy(() => import("../features/analytics/AnalyticsPage").then((m) => ({ default: m.AnalyticsPage })));
const CalibrationPage = lazy(() => import("../features/calibration/CalibrationPage").then((m) => ({ default: m.CalibrationPage })));
const InspectTagsPage = lazy(() => import("../features/inspect/InspectTagsPage").then((m) => ({ default: m.InspectTagsPage })));
const ConfigPage = lazy(() => import("../features/config/ConfigPage").then((m) => ({ default: m.ConfigPage })));
const AdminPage = lazy(() => import("../features/admin/AdminPage").then((m) => ({ default: m.AdminPage })));
const NavidromePage = lazy(() => import("../features/navidrome/NavidromePage").then((m) => ({ default: m.NavidromePage })));

/**
 * Main application router.
 *
 * Defines all routes and handles authentication redirects.
 */

// Protected route wrapper
function ProtectedRoute({ children }: { children: React.ReactNode }) {
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace />;
  }

  return <>{children}</>;
}

// Public route wrapper (redirects to home if already authenticated)
function PublicRoute({ children }: { children: React.ReactNode }) {
  if (isAuthenticated()) {
    return <Navigate to="/" replace />;
  }

  return <>{children}</>;
}

export function AppRouter() {
  return (
    <BrowserRouter>
      <Suspense fallback={<div style={{ padding: "20px" }}>Loading...</div>}>
        <Routes>
          {/* Public Routes */}
          <Route
            path="/login"
            element={
              <PublicRoute>
                <LoginPage />
              </PublicRoute>
            }
          />

          {/* Protected Routes - All wrapped in AppShell */}
          <Route
            path="/*"
            element={
              <ProtectedRoute>
                <AppShell>
                  <Routes>
                    <Route path="/" element={<DashboardPage />} />
                    <Route path="/tagger-status" element={<TaggerStatusPage />} />
                    <Route path="/browse" element={<BrowsePage />} />
                    <Route path="/analytics" element={<AnalyticsPage />} />
                    <Route path="/calibration" element={<CalibrationPage />} />
                    <Route path="/inspect" element={<InspectTagsPage />} />
                    <Route path="/config" element={<ConfigPage />} />
                    <Route path="/admin" element={<AdminPage />} />
                    <Route path="/navidrome" element={<NavidromePage />} />
                  </Routes>
                </AppShell>
              </ProtectedRoute>
            }
          />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
