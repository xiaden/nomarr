import { Box, Button, Typography } from "@mui/material";
import { NavLink, useNavigate } from "react-router-dom";

import { logout } from "../../shared/auth";

/**
 * Sidebar navigation component.
 *
 * Displays the app title, main navigation links, and logout button
 * in a fixed-width left sidebar.
 */

interface NavItem {
  path: string;
  label: string;
}

const SIDEBAR_WIDTH = 220;

const navItems: NavItem[] = [
  { path: "/", label: "Dashboard" },
  { path: "/browse", label: "Library" },
  { path: "/insights", label: "Insights" },
  { path: "/calibration", label: "Calibration" },
  { path: "/vector-search", label: "Vector Search" },
  { path: "/navidrome", label: "Navidrome" },
  { path: "/playlist-import", label: "Playlist Import" },
  { path: "/config", label: "Config" },
];

export { SIDEBAR_WIDTH };

export function Sidebar() {
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate("/login", { replace: true });
  };

  return (
    <Box
      component="nav"
      sx={{
        width: SIDEBAR_WIDTH,
        minWidth: SIDEBAR_WIDTH,
        height: "100vh",
        position: "sticky",
        top: 0,
        display: "flex",
        flexDirection: "column",
        bgcolor: "#151515",
        borderRight: 1,
        borderColor: "divider",
        py: 2,
      }}
    >
      {/* App title */}
      <Box sx={{ px: 2.5, mb: 3, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <Typography variant="h6" sx={{ fontWeight: 700 }}>
          Nomarr
        </Typography>
        <Typography
          component="span"
          sx={{ color: "success.main", fontSize: "0.6rem" }}
        >
          ●
        </Typography>
      </Box>

      {/* Nav links */}
      <Box sx={{ display: "flex", flexDirection: "column", gap: 0.5, px: 1, flex: 1 }}>
        {navItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === "/"}
            style={({ isActive }) => ({
              display: "block",
              padding: "0.6rem 1rem",
              borderRadius: "6px",
              textDecoration: "none",
              fontSize: "0.875rem",
              fontWeight: isActive ? 600 : 400,
              color: isActive ? "#fff" : "#999",
              backgroundColor: isActive ? "rgba(74, 158, 255, 0.12)" : "transparent",
              transition: "all 0.15s ease",
            })}
          >
            {item.label}
          </NavLink>
        ))}
      </Box>

      {/* Logout */}
      <Box sx={{ px: 1.5, mt: 2 }}>
        <Button
          onClick={handleLogout}
          variant="outlined"
          size="small"
          fullWidth
          sx={{ textTransform: "none", fontSize: "0.8rem" }}
        >
          Logout
        </Button>
      </Box>
    </Box>
  );
}
