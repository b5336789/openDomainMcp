import { NavLink, Outlet } from "react-router-dom";

const links = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/ingest", label: "Ingest" },
  { to: "/explore", label: "Explore" },
  { to: "/browse", label: "Browse / Edit" },
  { to: "/settings", label: "Settings" },
];

export default function App() {
  return (
    <div className="min-h-screen flex">
      <aside className="w-56 bg-slate-900 text-slate-100 p-4 space-y-1">
        <h1 className="text-lg font-semibold mb-4">openDomainMcp</h1>
        {links.map((l) => (
          <NavLink
            key={l.to}
            to={l.to}
            end={l.end}
            className={({ isActive }) =>
              `block rounded px-3 py-2 text-sm ${
                isActive ? "bg-slate-700 font-medium" : "hover:bg-slate-800"
              }`
            }
          >
            {l.label}
          </NavLink>
        ))}
        <p className="pt-6 text-xs text-slate-400">
          Domain knowledge workflow platform
        </p>
      </aside>
      <main className="flex-1 p-8 max-w-5xl">
        <Outlet />
      </main>
    </div>
  );
}
