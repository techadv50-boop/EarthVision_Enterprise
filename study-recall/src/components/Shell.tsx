import { useEffect } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useSession, useStudent } from "../store";

const links = [
  { to: "/study", label: "Study material" },
  { to: "/oral", label: "Oral test" },
  { to: "/written", label: "Written test" },
  { to: "/progress", label: "Progress" },
  { to: "/revision", label: "Revision" },
  { to: "/settings", label: "Settings" },
];

export function Shell() {
  const refresh = useSession((state) => state.refresh);
  const ready = useSession((state) => state.ready);
  const error = useSession((state) => state.error);
  const theme = useSession((state) => state.settings?.theme ?? "light");
  const setTheme = useSession((state) => state.setTheme);
  const student = useStudent();

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <div className="min-h-screen">
      <nav className="border-b border-line bg-card">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-3 px-4 py-3">
          <NavLink to="/" className="mr-2 text-lg font-semibold tracking-tight">
            Study Recall
          </NavLink>
          {links.map((link) => (
            <NavLink
              key={link.to}
              to={link.to}
              className={({ isActive }) =>
                `rounded-full px-3 py-1 text-sm ${isActive ? "bg-accent text-accent-ink" : "text-muted hover:text-ink"}`
              }
            >
              {link.label}
            </NavLink>
          ))}
          <div className="ml-auto flex items-center gap-3 text-sm">
            <span className="text-muted">{student ? student.displayName : "No student yet"}</span>
            <button
              type="button"
              className="rounded-full border border-line px-3 py-1"
              onClick={() => void setTheme(theme === "dark" ? "light" : "dark")}
            >
              {theme === "dark" ? "Light theme" : "Dark theme"}
            </button>
          </div>
        </div>
      </nav>
      <main className="mx-auto max-w-6xl px-4 py-8">
        {!ready ? <p>Opening your local study library…</p> : null}
        {error ? (
          <p className="mb-4 rounded-xl border border-danger/40 bg-danger/10 px-4 py-3">
            {error} Open Study Recall from the desktop window so it can use the local database.
          </p>
        ) : null}
        {ready ? <Outlet /> : null}
      </main>
    </div>
  );
}
