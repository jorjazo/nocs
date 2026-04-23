import { NavLink } from "react-router-dom";
import { useContext } from "react";
import { AuthContext } from "@/auth/AuthContext";
import { ConnectionPill } from "./ConnectionPill";

const LINKS: { to: string; label: string }[] = [
  { to: "/", label: "Dashboard" },
  { to: "/targets", label: "Targets" },
  { to: "/mount", label: "Mount" },
  { to: "/camera", label: "Camera" },
  { to: "/filter-wheel", label: "Filter wheel" },
  { to: "/focuser", label: "Focuser" },
  { to: "/plate-solve", label: "Plate solve" },
  { to: "/sequences", label: "Sequences" },
  { to: "/gallery", label: "Gallery" },
  { to: "/sessions", label: "Sessions" },
  { to: "/safety", label: "Safety" },
  { to: "/settings", label: "Settings" },
];

export function NavBar() {
  const { clearToken } = useContext(AuthContext);
  return (
    <nav
      style={{
        display: "flex",
        gap: 12,
        alignItems: "center",
        padding: "10px 16px",
        background: "var(--color-surface)",
        borderBottom: "1px solid var(--color-border)",
        position: "sticky",
        top: 0,
        zIndex: 10,
        flexWrap: "wrap",
      }}
    >
      <strong style={{ marginRight: 12 }}>NOCS</strong>
      <ul
        style={{
          display: "flex",
          gap: 8,
          listStyle: "none",
          margin: 0,
          padding: 0,
          flexWrap: "wrap",
        }}
      >
        {LINKS.map((l) => (
          <li key={l.to}>
            <NavLink
              to={l.to}
              end={l.to === "/"}
              style={({ isActive }) => ({
                padding: "4px 10px",
                borderRadius: 4,
                background: isActive ? "var(--color-surface-2)" : "transparent",
                color: isActive ? "var(--color-accent)" : "var(--color-text)",
                textDecoration: "none",
              })}
            >
              {l.label}
            </NavLink>
          </li>
        ))}
      </ul>
      <span style={{ marginLeft: "auto", display: "flex", gap: 12, alignItems: "center" }}>
        <ConnectionPill />
        <button type="button" onClick={clearToken} title="Clear token and sign out">
          Sign out
        </button>
      </span>
    </nav>
  );
}
