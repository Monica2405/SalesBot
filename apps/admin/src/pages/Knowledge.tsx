import { RowsTable } from "../components/RowsTable";

export function Knowledge() {
  return (
    <section>
      <h2>Knowledge base</h2>
      {/* TODO: add/edit answers; turn unanswered questions into knowledge items */}
      <RowsTable
        table="knowledge_items"
        columns={["question", "answer", "language", "is_active"]}
        orderBy="updated_at"
        empty="No answers yet."
      />
      <h3>Questions the agent could not answer</h3>
      <RowsTable
        table="unanswered_questions"
        columns={["created_at", "question", "language", "status"]}
        orderBy="created_at"
        empty="Nothing unanswered."
      />
    </section>
  );
}
