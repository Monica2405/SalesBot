import { useEffect, useState } from "react";
import { supabase } from "../lib/supabase";

// Mirrors salesbot_core.events.FUNNEL
const FUNNEL = [
  { type: "call_received", label: "Calls" },
  { type: "lead_captured", label: "Leads" },
  { type: "booking_created", label: "Bookings" },
  { type: "appointment_showed", label: "Shows" },
  { type: "payment_recorded", label: "Paid" },
] as const;

export function Metrics() {
  const [counts, setCounts] = useState<Record<string, number>>({});

  useEffect(() => {
    if (!supabase) return;
    const client = supabase;
    // TODO: move to a SQL view / RPC with date range, per-source and per-script-version splits.
    Promise.all(
      FUNNEL.map(({ type }) =>
        client
          .from("events")
          .select("id", { count: "exact", head: true })
          .eq("type", type)
          .then(({ count }) => [type, count ?? 0] as const),
      ),
    ).then((pairs) => setCounts(Object.fromEntries(pairs)));
  }, []);

  return (
    <section>
      <h2>Metrics</h2>
      <p className="muted">Funnel: every number comes from append-only events.</p>
      <div className="funnel">
        {FUNNEL.map(({ type, label }, i) => {
          const n = counts[type] ?? 0;
          const prev = i > 0 ? (counts[FUNNEL[i - 1].type] ?? 0) : null;
          return (
            <div key={type} className="stage">
              <span className="muted">{label}</span>
              <strong>{n}</strong>
              {prev ? <span className="muted">{Math.round((n / prev) * 100)}% of previous</span> : null}
            </div>
          );
        })}
      </div>
    </section>
  );
}
