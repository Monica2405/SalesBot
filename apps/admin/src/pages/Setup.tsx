import { RowsTable } from "../components/RowsTable";

export function Setup() {
  return (
    <section>
      <h2>Setup</h2>
      <h3>Business</h3>
      <RowsTable
        table="businesses"
        columns={["name", "pack_id", "phone_number", "timezone", "usage_cap_minutes"]}
        orderBy="created_at"
        empty="No business linked to this login."
      />
      <h3>Test call</h3>
      {/* TODO: browser test call (WebRTC to the voice agent), tagged source=test_call */}
      <button disabled>Start test call from browser (coming soon)</button>
      <h3>Integrations</h3>
      {/* TODO: Google Calendar connect, WhatsApp, phone number. Handled via apps/api. */}
      <p className="muted">Calendar, WhatsApp and phone number setup will live here.</p>
    </section>
  );
}
