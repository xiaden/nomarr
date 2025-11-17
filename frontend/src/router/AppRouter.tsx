import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "../components/layout/AppShell";
import { AdminPage } from "../pages/AdminPage";
import { AnalyticsPage } from "../pages/AnalyticsPage";
import { CalibrationPage } from "../pages/CalibrationPage";
import { ConfigPage } from "../pages/ConfigPage";
import { DashboardPage } from "../pages/DashboardPage";
import { InspectTagsPage } from "../pages/InspectTagsPage";
import { LibraryPage } from "../pages/LibraryPage";
import { LoginPage } from "../pages/LoginPage";
import { NavidromePage } from "../pages/NavidromePage";
import { QueuePage } from "../pages/QueuePage";
import { isAuthenticated } from "../shared/auth";

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
                  <Route path="/queue" element={<QueuePage />} />
                  <Route path="/library" element={<LibraryPage />} />
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
    </BrowserRouter>
  );
}
