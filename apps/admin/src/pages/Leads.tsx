import { RowsTable } from "../components/RowsTable";

export function Leads() {
  return (
    <section>
      <h2>Leads</h2>
      {/* TODO: stage changes (writes lead_events), lead score, follow-up status */}
      <RowsTable
        table="leads"
        columns={["created_at", "name", "phone", "service_id", "stage", "source", "estimated_value_inr"]}
        orderBy="created_at"
        empty="No leads yet."
      />
    </section>
  );
}
