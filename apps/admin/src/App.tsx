import { BrowserRouter, Navigate, Route, Routes } from "react-router";
import { Layout } from "./components/Layout";
import { supabaseConfigured } from "./lib/supabase";
import { useSession } from "./lib/useSession";
import { Calls } from "./pages/Calls";
import { Knowledge } from "./pages/Knowledge";
import { Leads } from "./pages/Leads";
import { Login } from "./pages/Login";
import { Metrics } from "./pages/Metrics";
import { Setup } from "./pages/Setup";

export default function App() {
  const session = useSession();

  if (!supabaseConfigured) {
    return (
      <div className="login">
        <p>
          Set <code>VITE_SUPABASE_URL</code> and <code>VITE_SUPABASE_ANON_KEY</code> in{" "}
          <code>apps/admin/.env</code> (see <code>.env.example</code>).
        </p>
      </div>
    );
  }
  if (session === undefined) return null;
  if (session === null) return <Login />;

  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout email={session.user.email} />}>
          <Route index element={<Navigate to="/calls" replace />} />
          <Route path="/calls" element={<Calls />} />
          <Route path="/leads" element={<Leads />} />
          <Route path="/knowledge" element={<Knowledge />} />
          <Route path="/metrics" element={<Metrics />} />
          <Route path="/setup" element={<Setup />} />
          <Route path="*" element={<Navigate to="/calls" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
