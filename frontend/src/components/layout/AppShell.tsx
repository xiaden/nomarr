import { Box, Typography } from "@mui/material";
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
    <Box
      sx={{
        minHeight: "100vh",
        bgcolor: "background.paper",
        color: "text.primary",
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* Top Bar */}
      <Box
        component="header"
        sx={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          px: 4,
          py: 2,
          bgcolor: "#252525",
          borderBottom: 1,
          borderColor: "divider",
        }}
      >
        <Typography variant="h5" sx={{ fontWeight: 600 }}>
          Nomarr
        </Typography>
        <Box
          sx={{
            display: "flex",
            alignItems: "center",
            gap: 1,
            fontSize: "0.875rem",
            color: "text.secondary",
          }}
        >
          <Typography
            component="span"
            sx={{ color: "success.main", fontSize: "0.75rem" }}
          >
            ●
          </Typography>
          <span>Online</span>
        </Box>
      </Box>

      {/* Navigation */}
      <NavTabs />

      {/* Main Content */}
      <Box component="main" sx={{ flex: 1 }}>
        {children}
      </Box>
    </Box>
  );
}
