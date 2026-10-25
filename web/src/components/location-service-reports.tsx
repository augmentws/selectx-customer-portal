"use client";

import { FileText } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { formatPestPacDate } from "@/components/service-order-list";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { errorMessage } from "@/lib/api/errors";
import { useLocationsListServiceOrders } from "@/lib/api/generated/locations/locations";
import {
  useReportsCreateServiceReport,
  useReportsListReportTemplates,
  useReportsListServiceReports,
} from "@/lib/api/generated/reports/reports";

function StartReport({ companyId, locationId }: { companyId: string; locationId: string }) {
  const router = useRouter();
  const templates = useReportsListReportTemplates(companyId);
  const orders = useLocationsListServiceOrders(locationId, { status: "all" });
  // One report per order: orders that have one link to it instead.
  const existing = useReportsListServiceReports(locationId);
  const reportByOrder = new Map(existing.data?.data.map((r) => [r.service_order_id, r.id]));
  // Service reports need a template with fields to edit.
  const usable = templates.data?.data.filter((t) => t.fields.length > 0) ?? [];
  const [templateId, setTemplateId] = useState("");
  const [orderId, setOrderId] = useState("");
  const create = useReportsCreateServiceReport({
    mutation: { onSuccess: (res) => router.push(`/service-reports/${res.data.id}`) },
  });
  const chosenTemplate = templateId || usable[0]?.id || "";

  if (templates.isSuccess && usable.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        No service report templates for this customer yet (a template needs report fields).
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-2">
          <Label htmlFor="sr-order">Service order</Label>
          <NativeSelect
            id="sr-order"
            value={orderId}
            disabled={!orders.data || !existing.data}
            onChange={(e) => setOrderId(e.target.value)}
          >
            <NativeSelectOption value="">Choose an order</NativeSelectOption>
            {orders.data?.data.map((o) => (
              <NativeSelectOption key={o.id} value={o.id} disabled={reportByOrder.has(o.id)}>
                {formatPestPacDate(o.work_date) || "No date"} · {o.service_code ?? "Order"} ·{" "}
                {o.order_number ?? o.pestpac_order_id}
                {reportByOrder.has(o.id) && " · has a report"}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="sr-template">Template</Label>
          <NativeSelect
            id="sr-template"
            value={chosenTemplate}
            onChange={(e) => setTemplateId(e.target.value)}
          >
            {usable.map((t) => (
              <NativeSelectOption key={t.id} value={t.id}>
                {t.name}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </div>
        <Button
          disabled={!orderId || !chosenTemplate || create.isPending}
          onClick={() =>
            create.mutate({
              locationId,
              data: { template_id: chosenTemplate, service_order_id: orderId },
            })
          }
        >
          <FileText aria-hidden />
          {create.isPending ? "Starting…" : "Start report"}
        </Button>
      </div>
      <p className="text-sm text-muted-foreground">
        Collects the location&apos;s notes and photos around the order&apos;s work date for you to
        pick from. An order has one report; orders that already have one are listed below.
      </p>
      {create.isError && (
        <Alert variant="destructive">
          <AlertDescription>{errorMessage(create.error)}</AlertDescription>
        </Alert>
      )}
    </div>
  );
}

/** Service reports at a location: start one from an order, and the existing ones. */
export function LocationServiceReports({
  companyId,
  locationId,
  canWrite,
}: {
  companyId: string;
  locationId: string;
  canWrite: boolean;
}) {
  const reports = useReportsListServiceReports(locationId);
  return (
    <div className="flex flex-col gap-4">
      {canWrite && <StartReport companyId={companyId} locationId={locationId} />}
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
