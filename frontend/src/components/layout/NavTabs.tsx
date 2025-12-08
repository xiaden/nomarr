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
  { path: "/queue", label: "Queue" },
  { path: "/library", label: "Library" },
  { path: "/browse", label: "Browse Files" },
  { path: "/analytics", label: "Analytics" },
  { path: "/calibration", label: "Calibration" },
  { path: "/inspect", label: "Inspect" },
  { path: "/config", label: "Config" },
  { path: "/admin", label: "Admin" },
  { path: "/navidrome", label: "Navidrome" },
];

export function NavTabs() {
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate("/login", { replace: true });
  };

  return (
    <nav style={styles.nav}>
      <div style={styles.navLinks}>
        {navItems.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === "/"}
            style={({ isActive }) => ({
              ...styles.navLink,
              ...(isActive ? styles.navLinkActive : {}),
            })}
          >
            {item.label}
          </NavLink>
        ))}
      </div>
      <button onClick={handleLogout} style={styles.logoutButton}>
        Logout
      </button>
    </nav>
  );
}

const styles = {
  nav: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    padding: "0 1rem",
    borderBottom: "1px solid #333",
  },
  navLinks: {
    display: "flex",
    gap: "1rem",
  },
  navLink: {
    padding: "1rem",
    textDecoration: "none",
    color: "#aaa",
    borderBottom: "2px solid transparent",
    transition: "color 0.2s, border-color 0.2s",
  },
  navLinkActive: {
    color: "#fff",
    borderBottomColor: "#4a9eff",
  },
  logoutButton: {
    padding: "0.5rem 1rem",
    backgroundColor: "#444",
    color: "#fff",
    border: "1px solid #666",
    borderRadius: "4px",
    cursor: "pointer",
    fontSize: "0.9rem",
    transition: "background-color 0.2s",
  } as React.CSSProperties,
};
