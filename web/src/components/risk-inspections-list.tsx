"use client";

import Link from "next/link";

import { ExportButton } from "@/components/export-button";
import { formatPestPacDate } from "@/components/service-order-list";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { errorMessage } from "@/lib/api/errors";
import type { RiskInspectionListItem } from "@/lib/api/generated/model";
import {
  useRiskInspectionsListCompanyRiskInspections,
  useRiskInspectionsListLocationRiskInspections,
} from "@/lib/api/generated/risk-inspections/risk-inspections";
import type { CsvColumn } from "@/lib/export-csv";

/** A 1-5 risk score: low (1-2), medium (3), high (4-5). */
export function RiskBadge({ risk, label }: { risk: number | null; label?: string }) {
  if (risk == null) return <span className="text-muted-foreground">—</span>;
  const variant = risk >= 4 ? "destructive" : risk === 3 ? "warning" : "success";
  return (
    <Badge variant={variant}>
      {label ? `${label} ` : ""}
      {risk}
    </Badge>
  );
}

const inspectedOn = (i: RiskInspectionListItem) =>
  i.inspected_at ? formatPestPacDate(i.inspected_at, true) : "";

function exportColumns(withStore: boolean): CsvColumn<RiskInspectionListItem>[] {
  return [
    { header: "Inspected", value: inspectedOn },
    ...(withStore
      ? [{ header: "Location", value: (i: RiskInspectionListItem) => i.location_name }]
      : []),
    { header: "Store", value: (i) => i.store_label },
    { header: "Inspector", value: (i) => i.inspector_name },
    { header: "Submission", value: (i) => i.submission_number },
    { header: "Work order", value: (i) => i.work_order_ref },
    { header: "RAMP", value: (i) => i.ramp_recommendation },
    { header: "Highest zone risk", value: (i) => i.highest_risk },
    { header: "Zones inspected", value: (i) => i.zones_inspected },
    { header: "Zones with activity", value: (i) => i.zones_with_activity },
  ];
}

function InspectionsTable({
  inspections,
  withStore,
  exportName,
}: {
  inspections: RiskInspectionListItem[];
  withStore: boolean;
  exportName: string;
}) {
  if (inspections.length === 0) {
    return (
      <p className="border border-border bg-card p-4 text-muted-foreground">
        No risk inspections yet.
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-sm text-muted-foreground">{inspections.length} risk inspections</p>
        <div className="ml-auto">
          <ExportButton name={exportName} rows={inspections} columns={exportColumns(withStore)} />
        </div>
      </div>
      <div className="border border-border bg-card px-4">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border text-xs text-muted-foreground">
            <tr>
              <th scope="col" className="py-2 pr-3 font-medium">
                Inspected
              </th>
              {withStore && (
                <th scope="col" className="py-2 pr-3 font-medium">
                  Location
                </th>
              )}
              <th scope="col" className="hidden py-2 pr-3 font-medium sm:table-cell">
                Inspector
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                RAMP
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                Highest risk
              </th>
              <th scope="col" className="hidden py-2 text-right font-medium sm:table-cell">
                Zones with activity
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {inspections.map((i) => (
              <tr key={i.id}>
                <td className="py-2 pr-3">
                  <Link
                    href={`/risk-inspections/${i.id}`}
                    className="font-medium text-primary hover:underline"
                  >
                    {inspectedOn(i) ||
                      `Submission ${i.submission_number ?? i.gocanvas_submission_id}`}
                  </Link>
                  {i.is_revision && (
                    <Badge variant="outline" className="ml-2">
                      Revised
                    </Badge>
                  )}
                </td>
                {withStore && <td className="py-2 pr-3">{i.location_name ?? i.store_label}</td>}
                <td className="hidden py-2 pr-3 sm:table-cell">{i.inspector_name ?? "—"}</td>
                <td className="py-2 pr-3">
                  {i.ramp_recommendation != null ? `RAMP ${i.ramp_recommendation}` : "—"}
                </td>
                <td className="py-2 pr-3">
                  <RiskBadge risk={i.highest_risk} />
                </td>
                <td className="hidden py-2 text-right tabular-nums sm:table-cell">
                  {i.zones_with_activity} of {i.zones_inspected}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ListState({
  query,
  children,
}: {
  query: { isPending: boolean; isError: boolean; error: unknown };
  children: () => React.ReactNode;
}) {
  if (query.isPending) return <p className="text-muted-foreground">Loading…</p>;
  if (query.isError) {
    return (
      <Alert variant="destructive">
        <AlertDescription>
          {errorMessage(query.error, "Could not load risk inspections.")}
        </AlertDescription>
      </Alert>
    );
  }
  return <>{children()}</>;
}

/** Every location's risk inspections under the company's bill-tos, newest first. */
export function CompanyRiskInspections({
  companyId,
  companyName,
}: {
  companyId: string;
  companyName: string;
}) {
  const query = useRiskInspectionsListCompanyRiskInspections(companyId);
  return (
    <ListState query={query}>
      {() => (
        <InspectionsTable
          inspections={query.data?.data ?? []}
          withStore
          exportName={`${companyName} risk inspections`}
        />
      )}
    </ListState>
  );
}

export function LocationRiskInspections({
  locationId,
  locationName,
}: {
  locationId: string;
  locationName: string;
}) {
  const query = useRiskInspectionsListLocationRiskInspections(locationId);
  return (
    <ListState query={query}>
      {() => (
        <InspectionsTable
          inspections={query.data?.data ?? []}
          withStore={false}
          exportName={`${locationName} risk inspections`}
        />
      )}
    </ListState>
  );
}
