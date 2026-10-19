import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";

// Everything prefixed VITE_ is shipped to the browser. Refuse to build if a service role key
// (which bypasses RLS) ever ends up there. See SECURITY.md.
function assertNoServiceRoleKey(env: Record<string, string>) {
  for (const [name, value] of Object.entries(env)) {
    if (!name.startsWith("VITE_")) continue;
    if (/SERVICE_ROLE/i.test(name)) {
      throw new Error(`${name}: the service role key must never be a VITE_ variable`);
    }
    const payload = value.split(".")[1];
    if (!payload) continue;
    try {
      const claims = JSON.parse(Buffer.from(payload, "base64url").toString("utf8"));
      if (claims?.role === "service_role") {
        throw new Error(`${name} holds a service_role JWT; use the anon key`);
      }
    } catch (e) {
      if (e instanceof Error && e.message.includes("service_role")) throw e;
    }
    if (value.startsWith("sb_secret_")) {
      throw new Error(`${name} holds a Supabase secret key; use the publishable/anon key`);
    }
  }
}

export default defineConfig(({ mode }) => {
  assertNoServiceRoleKey(loadEnv(mode, process.cwd(), "VITE_"));
  return { plugins: [react()] };
});
