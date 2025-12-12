/**
 * MUI theme configuration for Nomarr.
 *
 * Defines the design system including colors, typography, spacing, component defaults,
 * and global styles (including scrollbar customization).
 * Uses dark mode to match the existing application aesthetic.
 */

import { createTheme } from "@mui/material/styles";

export const theme = createTheme({
  palette: {
    mode: "dark",
    primary: {
      main: "#4a9eff", // Existing accent blue
      light: "#7bb8ff",
      dark: "#2d7ed1",
    },
    secondary: {
      main: "#6c757d", // Existing secondary gray
      light: "#949ba3",
      dark: "#4e555b",
    },
    background: {
      default: "#0a0a0a", // Very dark background
      paper: "#1a1a1a", // Slightly lighter for cards/sections
    },
    text: {
      primary: "#ffffff",
      secondary: "#888888",
    },
    error: {
      main: "#dc3545",
    },
    success: {
      main: "#28a745",
    },
    warning: {
      main: "#ffc107",
    },
    info: {
      main: "#17a2b8",
    },
    divider: "#333333",
  },
  typography: {
    fontFamily: [
      "-apple-system",
      "BlinkMacSystemFont",
      '"Segoe UI"',
      "Roboto",
      '"Helvetica Neue"',
      "Arial",
      "sans-serif",
    ].join(","),
    h1: {
      fontSize: "2rem",
      fontWeight: 600,
    },
    h2: {
      fontSize: "1.5rem",
      fontWeight: 600,
    },
    h3: {
      fontSize: "1.25rem",
      fontWeight: 600,
    },
    body1: {
      fontSize: "1rem",
    },
    body2: {
      fontSize: "0.875rem",
    },
  },
  shape: {
    borderRadius: 8,
  },
  spacing: 8, // Base spacing unit (8px)
  components: {
    MuiButton: {
      styleOverrides: {
        root: {
          textTransform: "none", // Disable uppercase transformation
          fontWeight: 500,
        },
      },
      defaultProps: {
        disableElevation: true,
      },
    },
    MuiCard: {
      styleOverrides: {
        root: {
          backgroundImage: "none", // Remove default gradient
          backgroundColor: "#1a1a1a", // background.paper
          border: "1px solid #333333", // divider
        },
      },
      defaultProps: {
        elevation: 0,
      },
    },
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: "none", // Remove default gradient
        },
      },
      defaultProps: {
        elevation: 0,
      },
    },
    MuiTypography: {
      styleOverrides: {
        h6: {
          fontWeight: 600,
        },
      },
    },
    MuiCssBaseline: {
      styleOverrides: {
        "*": {
          margin: 0,
          padding: 0,
          boxSizing: "border-box",
        },
        body: {
          margin: 0,
          lineHeight: 1.5,
        },
        "::-webkit-scrollbar": {
          width: "8px",
          height: "8px",
        },
        "::-webkit-scrollbar-track": {
          background: "#1a1a1a", // background.paper
        },
        "::-webkit-scrollbar-thumb": {
          background: "#333333", // divider
          borderRadius: "4px",
        },
        "::-webkit-scrollbar-thumb:hover": {
          background: "#888888", // text.secondary
        },
      },
    },
  },
});
