import { Box, Button } from "@mui/material";
import { NavLink, useNavigate } from "react-router-dom";

import { logout } from "../../shared/auth";

/**
 * Navigation tabs component.
 *
 * Displays main navigation links for the app.
 */

interface NavItem {
  path: string;
  label: string;
}

const navItems: NavItem[] = [
  { path: "/", label: "Dashboard" },
  { path: "/tagger-status", label: "Tagger Status" },
  { path: "/browse", label: "Browse Files" },
  { path: "/insights", label: "Insights" },
  { path: "/calibration", label: "Calibration" },
  { path: "/config", label: "Config" },
  { path: "/admin", label: "Admin" },
];

export function NavTabs() {
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate("/login", { replace: true });
  };

  return (
    <Box
      component="nav"
      sx={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        px: 2,
        borderBottom: 1,
        borderColor: "divider",
      }}
    >
      <Box sx={{ display: "flex", gap: 2 }}>
        {navItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === "/"}
            style={({ isActive }) => ({
              padding: "1rem",
              textDecoration: "none",
              borderBottom: "2px solid transparent",
              borderBottomColor: isActive ? "#4a9eff" : "transparent",
              color: isActive ? "#fff" : "#aaa",
              transition: "color 0.2s, border-color 0.2s",
            })}
          >
            {item.label}
          </NavLink>
        ))}
      </Box>
      <Button
        onClick={handleLogout}
        variant="outlined"
        size="small"
        sx={{
          textTransform: "none",
        }}
      >
        Logout
      </Button>
    </Box>
  );
}
