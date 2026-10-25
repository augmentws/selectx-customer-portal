"use client";

import { DocumentRow } from "@/components/location-documents";
import { formatPestPacDate } from "@/components/service-order-list";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { errorMessage } from "@/lib/api/errors";
import { useLocationsListConditions } from "@/lib/api/generated/locations/locations";
import type { ConditionRead } from "@/lib/api/generated/model";

function SeverityBadge({ severity }: { severity: string | null }) {
  if (!severity) return null;
  const variant =
    severity === "High" || severity === "Critical"
      ? "destructive"
      : severity === "Medium"
        ? "warning"
        : "secondary";
  return <Badge variant={variant}>{severity} severity</Badge>;
}

function ConditionCard({ condition: c }: { condition: ConditionRead }) {
  const open = c.status === "Open";
  const where = [c.area_hierarchy ?? c.area, c.specific_area].filter(Boolean).join(" · ");
  return (
    <li className="p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{c.condition ?? "Condition"}</span>
        {c.condition_type && (
          <span className="text-sm text-muted-foreground">{c.condition_type}</span>
        )}
        <Badge variant={open ? "secondary" : "success"}>{c.status ?? "Unknown"}</Badge>
        <SeverityBadge severity={c.severity} />
        {c.category && <Badge variant="outline">{c.category}</Badge>}
        {c.responsibility && <Badge variant="outline">Responsibility: {c.responsibility}</Badge>}
      </div>
      <div className="mt-1 flex flex-wrap gap-x-4 text-sm text-muted-foreground">
        {where && <span>{where}</span>}
        {c.detail && <span>{c.detail}</span>}
        <span>IssueID {c.pestpac_issue_id}</span>
        {c.date_opened && (
          <span>
            Opened {formatPestPacDate(c.date_opened)}
            {c.opened_by_user && ` by ${c.opened_by_user}`}
          </span>
        )}
        {c.date_closed && <span>Closed {formatPestPacDate(c.date_closed)}</span>}
      </div>

      {c.action && (
        <details className="mt-2">
          <summary className="cursor-pointer text-sm text-primary hover:underline">
            Recommended action
          </summary>
          <p className="mt-2 border-l-2 border-border pl-4 text-sm whitespace-pre-line">
            {/* PestPac separates bullet lines with bare carriage returns. */}
            {c.action.replace(/\r\n?/g, "\n")}
          </p>
        </details>
      )}

      {c.inspections.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer text-sm text-primary hover:underline">
            Inspections ({c.inspections.length})
          </summary>
          <ol className="mt-2 flex flex-col gap-2 border-l-2 border-border pl-4 text-sm">
            {c.inspections.map((i, n) => (
              <li key={n}>
                <span className="text-muted-foreground">
                  {formatPestPacDate(i.detail_date, true)}
                  {i.username && ` · ${i.username}`}
                  {i.status && ` · ${i.status}`}
                  {i.pestpac_order_id !== null && ` · OrderID ${i.pestpac_order_id}`}
                </span>
                {i.comment && <p>{i.comment}</p>}
              </li>
            ))}
          </ol>
        </details>
      )}

      {c.documents.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer text-sm text-primary hover:underline">
            Photos and documents ({c.documents.length})
          </summary>
          <ul className="mt-2 divide-y divide-border border-l-2 border-border">
            {c.documents.map((doc) => (
              <DocumentRow key={doc.id} doc={doc} />
            ))}
          </ul>
        </details>
      )}
    </li>
  );
}

/** The location's PestPac conditions (issues), open first. Filled by "Sync location". */
export function LocationConditions({ locationId }: { locationId: string }) {
  const conditions = useLocationsListConditions(locationId);
  const list = conditions.data?.data;
  const openCount = list?.filter((c) => c.status === "Open").length ?? 0;
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-xl">Conditions{list && ` (${openCount} open)`}</h2>
      {conditions.isPending && <p className="text-muted-foreground">Loading…</p>}
      {conditions.isError && (
        <Alert variant="destructive">
          <AlertDescription>
            {errorMessage(conditions.error, "Could not load conditions.")}
          </AlertDescription>
        </Alert>
      )}
      {list && (
        <ul className="divide-y divide-border border border-border bg-card">
          {list.length === 0 && (
            <li className="p-4 text-muted-foreground">
              No conditions recorded. Sync location to fetch open conditions from PestPac.
            </li>
          )}
          {list.map((c) => (
            <ConditionCard key={c.id} condition={c} />
          ))}
        </ul>
      )}
    </section>
  );
}
