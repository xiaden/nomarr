import type { ReactNode } from "react";

import { NavTabs } from "./NavTabs";

/**
 * Main application shell component.
 *
 * Provides the overall layout structure with:
 * - Top bar with app title
 * - Navigation tabs
 * - Main content area
 */

interface AppShellProps {
  children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  return (
    <div style={styles.container}>
      {/* Top Bar */}
      <header style={styles.header}>
        <h1 style={styles.title}>Nomarr</h1>
        <div style={styles.status}>
          <span style={styles.statusIndicator}>●</span>
          <span>Online</span>
        </div>
      </header>

      {/* Navigation */}
      <NavTabs />

      {/* Main Content */}
      <main style={styles.main}>{children}</main>
    </div>
  );
}

const styles = {
  container: {
    minHeight: "100vh",
    backgroundColor: "#1a1a1a",
    color: "#fff",
    display: "flex",
    flexDirection: "column" as const,
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "1rem 2rem",
    backgroundColor: "#252525",
    borderBottom: "1px solid #333",
  },
  title: {
    margin: 0,
    fontSize: "1.5rem",
    fontWeight: 600,
  },
  status: {
    display: "flex",
    alignItems: "center",
    gap: "0.5rem",
    fontSize: "0.875rem",
    color: "#aaa",
  },
  statusIndicator: {
    color: "#4ade80",
    fontSize: "0.75rem",
  },
  main: {
    flex: 1,
    overflow: "auto",
  },
};
