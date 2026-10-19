import { NavLink, Outlet } from "react-router";
import { supabase } from "../lib/supabase";

const NAV = [
  { to: "/calls", label: "Calls" },
  { to: "/leads", label: "Leads" },
  { to: "/knowledge", label: "Knowledge base" },
  { to: "/metrics", label: "Metrics" },
  { to: "/setup", label: "Setup" },
];

export function Layout({ email }: { email: string | undefined }) {
  return (
    <div className="shell">
      <aside>
        <h1>SalesBot</h1>
        <nav>
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to}>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <footer>
          <span className="muted">{email}</span>
          <button onClick={() => supabase?.auth.signOut()}>Sign out</button>
        </footer>
      </aside>
      <main>
        <Outlet />
      </main>
    </div>
  );
}
