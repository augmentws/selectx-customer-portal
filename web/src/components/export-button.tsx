"use client";

import { Download } from "lucide-react";

import { Button } from "@/components/ui/button";
import { type CsvColumn, downloadCsv } from "@/lib/export-csv";

/** Downloads `rows` as CSV. Lists pass every row matching their filter, not just the page. */
export function ExportButton<T>({
  name,
  rows,
  columns,
}: {
  /** Names the file: "locations" downloads as locations-2026-10-29.csv. */
  name: string;
  rows: readonly T[];
  columns: readonly CsvColumn<T>[];
}) {
  return (
    <Button
      variant="outline"
      size="sm"
      disabled={rows.length === 0}
      onClick={() => downloadCsv(name, rows, columns)}
    >
      <Download aria-hidden />
      Export CSV
    </Button>
  );
}
