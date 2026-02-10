import { Box } from "@mui/material";
import type { ReactNode } from "react";

import { Sidebar, SIDEBAR_WIDTH } from "./Sidebar";

/**
 * Main application shell component.
 *
 * Provides the overall layout structure with:
 * - Left sidebar navigation
 * - Main content area
 */

interface AppShellProps {
  children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  return (
    <Box
      sx={{
        minHeight: "100vh",
        bgcolor: "background.paper",
        color: "text.primary",
        display: "flex",
        flexDirection: "row",
      }}
    >
      {/* Sidebar */}
      <Sidebar />

      {/* Main Content */}
      <Box
        component="main"
        sx={{
          flex: 1,
          minWidth: 0,
          width: `calc(100% - ${SIDEBAR_WIDTH}px)`,
          overflow: "auto",
        }}
      >
        {children}
      </Box>
    </Box>
  );
}
