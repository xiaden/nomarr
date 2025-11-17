import { NavLink } from "react-router-dom";

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
  { path: "/analytics", label: "Analytics" },
  { path: "/calibration", label: "Calibration" },
  { path: "/inspect", label: "Inspect" },
  { path: "/config", label: "Config" },
  { path: "/admin", label: "Admin" },
  { path: "/navidrome", label: "Navidrome" },
];

export function NavTabs() {
  return (
    <nav style={styles.nav}>
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
    </nav>
  );
}

const styles = {
  nav: {
    display: "flex",
    gap: "1rem",
    padding: "0 1rem",
    borderBottom: "1px solid #333",
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
};
