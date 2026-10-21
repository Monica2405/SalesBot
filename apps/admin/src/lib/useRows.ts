import { useEffect, useState } from "react";
import { supabase } from "./supabase";

type Row = Record<string, unknown>;

/** Read rows from a table. RLS limits results to the signed-in owner's business. */
export function useRows(table: string, columns: string, orderBy: string) {
  const [rows, setRows] = useState<Row[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!supabase) return;
    supabase
      .from(table)
      .select(columns)
      .order(orderBy, { ascending: false })
      .limit(100)
      .then(({ data, error }) => {
        setRows((data as unknown as Row[]) ?? []);
        setError(error?.message ?? null);
        setLoading(false);
      });
  }, [table, columns, orderBy]);

  return { rows, error, loading };
}
