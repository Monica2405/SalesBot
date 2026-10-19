import { RowsTable } from "../components/RowsTable";

export function Calls() {
  return (
    <section>
      <h2>Calls</h2>
      {/* TODO: call detail with transcript, signed recording URL, cost breakdown */}
      <RowsTable
        table="calls"
        columns={["started_at", "from_number", "language", "source", "outcome", "duration_seconds"]}
        orderBy="started_at"
        empty="No calls yet."
      />
    </section>
  );
}
