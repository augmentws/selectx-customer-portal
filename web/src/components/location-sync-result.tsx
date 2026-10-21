import { CheckCircle2 } from "lucide-react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import type { LocationSyncSummary } from "@/lib/api/generated/model";

export function LocationSyncResult({
  summary,
  label,
}: {
  summary: LocationSyncSummary;
  label: string;
}) {
  const changes = [
    summary.added && `${summary.added} added`,
    summary.updated && `${summary.updated} updated`,
    summary.removed && `${summary.removed} removed`,
  ].filter(Boolean);
  return (
    <Alert variant="success" role="status">
      <CheckCircle2 aria-hidden />
      <AlertDescription>
        {label}: {summary.total} {summary.total === 1 ? "location" : "locations"} from PestPac
        {changes.length > 0 && ` (${changes.join(", ")})`}.
      </AlertDescription>
    </Alert>
  );
}
