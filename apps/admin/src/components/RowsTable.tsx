import { useRows } from "../lib/useRows";

type Props = { table: string; columns: string[]; orderBy: string; empty: string };

export function RowsTable({ table, columns, orderBy, empty }: Props) {
  const { rows, error, loading } = useRows(table, columns.join(","), orderBy);

  if (loading) return <p>Loading…</p>;
  if (error) return <p className="error">{error}</p>;
  if (rows.length === 0) return <p className="muted">{empty}</p>;

  return (
    <table>
      <thead>
        <tr>
          {columns.map((c) => (
            <th key={c}>{c}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr key={String(row.id ?? i)}>
            {columns.map((c) => (
              <td key={c}>{formatCell(row[c])}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function formatCell(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
