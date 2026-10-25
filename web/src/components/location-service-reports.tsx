"use client";

import Link from "next/link";

import { formatPestPacDate } from "@/components/service-order-list";
import { Badge } from "@/components/ui/badge";
import { errorMessage } from "@/lib/api/errors";
import { useReportsListServiceReports } from "@/lib/api/generated/reports/reports";

/** The location's service reports. They're started from an order (Service orders tab, or a
 * bill-to's or company's posted orders). */
export function LocationServiceReports({
  locationId,
  canStart,
}: {
  locationId: string;
  /** Whether to say where reports are started (the user can start them). */
  canStart: boolean;
}) {
  const reports = useReportsListServiceReports(locationId);
  return (
    <div className="flex flex-col gap-4">
      {canStart && (
        <p className="text-sm text-muted-foreground">
          Start a report from its order on the Service orders tab. An order has one report; changes
          are new versions of it.
        </p>
      )}
      {reports.data && reports.data.data.length === 0 && (
        <p className="text-sm text-muted-foreground">No service reports yet.</p>
      )}
      {reports.isError && (
        <p className="text-sm text-destructive">
          {errorMessage(reports.error, "Could not load service reports.")}
        </p>
      )}
      {reports.data && reports.data.data.length > 0 && (
        <ul className="divide-y divide-border border border-border">
          {reports.data.data.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-2 p-3 text-sm">
              <Link
                href={`/service-reports/${r.id}`}
                className="font-medium text-primary hover:underline"
              >
                {r.template_name}
              </Link>
              <span className="text-muted-foreground">
                Order {r.order_number ?? "—"}
                {r.work_date && ` · ${formatPestPacDate(r.work_date)}`}
              </span>
              <Badge
                variant={
                  r.status === "final"
                    ? "success"
                    : r.status === "superseded"
                      ? "outline"
                      : "secondary"
                }
              >
                {{ final: "Final", superseded: "Superseded", drafting: "Drafting" }[r.status] ??
                  "Draft"}
              </Badge>
              {r.revision > 1 && <Badge variant="outline">Revision {r.revision}</Badge>}
              {r.has_pdf && (
                <a
                  href={`/api/bff/v1/service-reports/${r.id}/pdf`}
                  target="_blank"
                  rel="noopener"
                  className="text-primary hover:underline"
                >
                  PDF
                </a>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
