import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "../components/layout/AppShell";
import { useAuthRedirect } from "../hooks/useAuthRedirect";
import { isAuthenticated } from "../shared/auth";

// Lazy-loaded pages for code splitting
const LoginPage = lazy(() => import("../features/auth/LoginPage").then((m) => ({ default: m.LoginPage })));
const DashboardPage = lazy(() => import("../features/dashboard/DashboardPage").then((m) => ({ default: m.DashboardPage })));
const BrowsePage = lazy(() => import("../features/browse/BrowsePage").then((m) => ({ default: m.BrowsePage })));
const InsightsPage = lazy(() => import("../features/insights/InsightsPage").then((m) => ({ default: m.InsightsPage })));
const CalibrationPage = lazy(() => import("../features/calibration/CalibrationPage").then((m) => ({ default: m.CalibrationPage })));
const ConfigPage = lazy(() => import("../features/config/ConfigPage").then((m) => ({ default: m.ConfigPage })));
const NavidromePage = lazy(() => import("../features/navidrome/NavidromePage").then((m) => ({ default: m.NavidromePage })));
const PlaylistImportPage = lazy(() => import("../features/playlist-import/PlaylistImportPage").then((m) => ({ default: m.PlaylistImportPage })));

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
      <AuthManager />
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
                    <Route path="/browse" element={<BrowsePage />} />
                    <Route path="/insights" element={<InsightsPage />} />
                    <Route path="/calibration" element={<CalibrationPage />} />
                    <Route path="/config" element={<ConfigPage />} />
                    <Route path="/navidrome" element={<NavidromePage />} />
                    <Route path="/playlist-import" element={<PlaylistImportPage />} />
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

// Component to manage global auth redirects
function AuthManager() {
  useAuthRedirect();
  return null;
}
