import { Badge } from "@/components/ui/badge";
import type { NoteRead } from "@/lib/api/generated/model";
import { cn } from "@/lib/utils";

/** PestPac notes, newest first as the API returns them. */
export function NoteList({
  notes,
  empty,
  compact = false,
}: {
  notes: NoteRead[];
  empty: string;
  compact?: boolean;
}) {
  if (notes.length === 0) {
    return <p className={cn("text-sm text-muted-foreground", !compact && "p-4")}>{empty}</p>;
  }
  return (
    <ul className={cn("flex flex-col", compact ? "gap-3" : "divide-y divide-border")}>
      {notes.map((note) => (
        <li key={note.id} className={compact ? undefined : "p-4"}>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            {note.note_code && <Badge variant="outline">{note.note_code}</Badge>}
            <span className="font-medium">{note.created_by_name ?? "Unknown author"}</span>
            {note.note_date && (
              // Wall-clock time from PestPac, shown as-is.
              <span className="text-muted-foreground">
                {new Date(note.note_date).toLocaleString(undefined, {
                  dateStyle: "medium",
                  timeStyle: "short",
                })}
              </span>
            )}
            {!compact && note.pestpac_order_id !== null && (
              <span className="text-muted-foreground">
                · OrderID {note.pestpac_order_id}
                {note.pestpac_invoice_id !== null && ` · Invoice ${note.pestpac_invoice_id}`}
              </span>
            )}
          </div>
          <p className="mt-1 whitespace-pre-line text-sm">{note.note || "(empty note)"}</p>
        </li>
      ))}
    </ul>
  );
}
