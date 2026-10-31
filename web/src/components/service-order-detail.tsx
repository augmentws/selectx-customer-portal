"use client";

import { useParams } from "next/navigation";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { ConditionCard } from "@/components/location-conditions";
import { DocumentRow } from "@/components/location-documents";
import { InvoiceRow } from "@/components/location-invoices";
import { NoteList } from "@/components/note-list";
import { ReportAction, useServiceReportTemplates } from "@/components/report-action";
import { formatPestPacDate, OrderStatusBadge } from "@/components/service-order-list";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { errorMessage } from "@/lib/api/errors";
import { useInvoicesGetInvoice } from "@/lib/api/generated/invoices/invoices";
import type {
  InspectionFindingRead,
  OrderCondition,
  ServiceOrderDetail,
} from "@/lib/api/generated/model";
import {
  useServiceOrdersGetServiceOrder,
  useServiceOrdersListRelated,
} from "@/lib/api/generated/service-orders/service-orders";
import { usePermissions } from "@/lib/permissions";
import { useDocumentTitle } from "@/lib/use-document-title";

const SAME_DAY_HELP = "Logged at this store within a day of the work date; PestPac didn't link it.";

/** Marks items PestPac doesn't link to the order but that were logged around its work date. */
function SameDay() {
  return (
    <Badge variant="outline" title={SAME_DAY_HELP}>
      Same day
    </Badge>
  );
}

const CONDITION_LINK: Record<OrderCondition["link"], React.ReactNode> = {
  opened: <Badge variant="outline">Opened on this order</Badge>,
  inspected: <Badge variant="outline">Inspected on this order</Badge>,
  same_day: <SameDay />,
};

function Instructions({ order }: { order: ServiceOrderDetail }) {
  const items = [
    ["Location instructions", order.location_instructions],
    ["Service instructions", order.service_instructions],
    ["Order instructions", order.order_instructions],
    ["Technician comment", order.technician_comment],
  ].filter((item): item is [string, string] => Boolean(item[1]));
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">No instructions or technician comment.</p>;
  }
  return (
    <dl className="flex flex-col gap-3">
      {items.map(([label, text]) => (
        <div key={label}>
          <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
          <dd className="text-sm whitespace-pre-line">{text}</dd>
        </div>
      ))}
    </dl>
  );
}

/** "needs_improvement" → "Needs improvement". */
function label(value: string): string {
  const text = value.replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

const LEVEL_BADGE: Record<string, "success" | "warning" | "destructive" | "outline"> = {
  none: "success",
  low: "outline",
  moderate: "warning",
  heavy: "destructive",
  satisfactory: "success",
  needs_improvement: "warning",
  poor: "destructive",
  intact: "success",
  compromised: "warning",
  open: "warning",
  in_progress: "outline",
  repaired: "success",
};

function Level({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-muted-foreground">Not assessed</span>;
  return <Badge variant={LEVEL_BADGE[value] ?? "outline"}>{label(value)}</Badge>;
}

const ITEM_GROUPS = [
  ["structural", "Structural"],
  ["sanitation", "Sanitation"],
  ["pest", "Other pests"],
] as const;

/**
 * The visit's findings as read from its notes by the LLM: internal to Select (the report's
 * narrative never shows these levels).
 */
function Findings({ findings: f }: { findings: InspectionFindingRead }) {
  const facts: [string, React.ReactNode][] = [
    ["Visit type", label(f.visit_type)],
    ["Rodent activity", <Level key="a" value={f.rodent_activity} />],
    ["Exclusion", <Level key="e" value={f.exclusion_status} />],
    ["Sanitation", <Level key="s" value={f.sanitation_rating} />],
    ["Species", f.rodent_species.map(label).join(", ") || "—"],
    ["Evidence", f.rodent_evidence.map(label).join(", ") || "—"],
    ["Rodents captured", f.rodents_captured ?? "—"],
    ["Devices serviced", f.devices_serviced ?? "—"],
    ["Activity locations", f.activity_locations.join("; ") || "—"],
    ["Activity zones", f.activity_zone_names.join(", ") || "—"],
  ];
  return (
    <div className="flex flex-col gap-4">
      {f.summary && <p className="text-sm">{f.summary}</p>}
      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {facts.map(([name, value]) => (
          <div key={name}>
            <dt className="text-xs font-medium text-muted-foreground">{name}</dt>
            <dd className="text-sm">{value}</dd>
          </div>
        ))}
      </dl>
      {ITEM_GROUPS.map(([kind, title]) => {
        const items = f.items.filter((i) => i.kind === kind);
        if (items.length === 0) return null;
        return (
          <div key={kind} className="flex flex-col gap-2">
            <h3 className="text-sm font-medium">
              {title} ({items.length})
            </h3>
            <ul className="divide-y divide-border border border-border">
              {items.map((i, n) => (
                <li key={n} className="flex flex-wrap items-center gap-2 px-3 py-2 text-sm">
                  <span className="font-medium">{label(i.category)}</span>
                  {i.location && <span className="text-muted-foreground">{i.location}</span>}
                  {i.zone_name && <Badge variant="outline">{i.zone_name}</Badge>}
                  {i.issue && <span className="basis-full">{i.issue}</span>}
                  <span className="ml-auto">
                    <Level value={i.status ?? i.severity} />
                  </span>
                </li>
              ))}
            </ul>
          </div>
        );
      })}
      <p className="text-xs text-muted-foreground">
        Read from the notes{" "}
        {f.source === "report_draft" ? "when the report was drafted" : "by extraction"} ·{" "}
        {new Date(f.extracted_at).toLocaleString()} · {f.model}. Internal: not shown to the
        customer.
      </p>
    </div>
  );
}

/** The invoice that billed the order: shown with billing:read, once it's stored. */
function OrderInvoice({ invoiceId }: { invoiceId: string }) {
  const invoice = useInvoicesGetInvoice(invoiceId);
  if (invoice.isPending) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (invoice.isError) {
    return (
      <Alert variant="destructive">
        <AlertDescription>
          {errorMessage(invoice.error, "Could not load the invoice.")}
        </AlertDescription>
      </Alert>
    );
  }
  return (
    <ul className="border border-border">
      <InvoiceRow invoice={invoice.data.data} />
    </ul>
  );
}

/**
 * One service order: its details and instructions, then what was logged around it (documents,
 * conditions, notes) and, with billing:read, its invoice. PestPac links few items to orders,
 * so the store's items from within a day of the work date are included, marked "Same day".
 */
export function ServiceOrderDetailPage() {
  const { orderId } = useParams<{ orderId: string }>();
  const { can } = usePermissions();
  const order = useServiceOrdersGetServiceOrder(orderId);
  const related = useServiceOrdersListRelated(orderId);
  const o = order.data?.data;
  const operatorId = o?.trail.find((c) => c.kind === "operator")?.id;
  const companyId = o?.trail.find((c) => c.kind === "company")?.id;
  const templates = useServiceReportTemplates(companyId, operatorId);
  useDocumentTitle(o && `Order ${o.order_number ?? o.pestpac_order_id}`, o?.location_name);

  if (order.isPending) return <p className="text-muted-foreground">Loading…</p>;
  if (order.isError || !o) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{errorMessage(order.error, "Service order not found.")}</AlertDescription>
      </Alert>
    );
  }
  const canBilling = operatorId !== undefined && can("billing:read", operatorId);
  const r = related.data?.data;
  const orderNotes = r?.notes.filter((n) => n.link === "order") ?? [];
  const sameDayNotes = r?.notes.filter((n) => n.link === "same_day") ?? [];

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Breadcrumbs trail={o.trail} />
        <h1 className="mt-2 flex flex-wrap items-center gap-3 text-3xl">
          Order {o.order_number ?? o.pestpac_order_id}
          <OrderStatusBadge order={o} />
        </h1>
        <p className="text-muted-foreground">
          {[
            formatPestPacDate(o.work_date, true) || "No work date",
            o.service_code,
            o.technician_name ?? "No technician",
            `OrderID ${o.pestpac_order_id}`,
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
        {o.description && <p className="text-sm text-muted-foreground">{o.description}</p>}
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <ReportAction
            orderId={o.id}
            locationId={o.location_id}
            reportId={o.report_id}
            templates={templates}
          />
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Instructions</CardTitle>
        </CardHeader>
        <CardContent>
          <Instructions order={o} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Findings</CardTitle>
        </CardHeader>
        <CardContent>
          {o.findings ? (
            <Findings findings={o.findings} />
          ) : (
            <p className="text-sm text-muted-foreground">
              Not read yet: findings come from drafting the order&apos;s report.
            </p>
          )}
        </CardContent>
      </Card>

      {related.isError && (
        <Alert variant="destructive">
          <AlertDescription>
            {errorMessage(related.error, "Could not load the order's documents and conditions.")}
          </AlertDescription>
        </Alert>
      )}
      {related.isPending && <p className="text-muted-foreground">Loading documents…</p>}
      {r && (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Documents and photos ({r.documents.length})</CardTitle>
            </CardHeader>
            <CardContent>
              {r.documents.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No documents linked to this order or logged that day.
                </p>
              ) : (
                <ul className="divide-y divide-border border border-border">
                  {r.documents.map((d) => (
                    <DocumentRow key={d.id} doc={d} extra={d.link === "same_day" && <SameDay />} />
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Conditions ({r.conditions.length})</CardTitle>
            </CardHeader>
            <CardContent>
              {r.conditions.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No conditions opened or inspected on this order or that day.
                </p>
              ) : (
                <ul className="divide-y divide-border border border-border">
                  {r.conditions.map((c) => (
                    <ConditionCard key={c.id} condition={c} extra={CONDITION_LINK[c.link]} />
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Notes ({r.notes.length})</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <NoteList notes={orderNotes} empty="No notes linked to this order." compact />
              {sameDayNotes.length > 0 && (
                <div className="flex flex-col gap-2">
                  <h3 className="text-sm font-medium">
                    Same day at this store <SameDay />
                  </h3>
                  <NoteList notes={sameDayNotes} empty="" compact />
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}

      {canBilling && (
        <Card>
          <CardHeader>
            <CardTitle>Invoice</CardTitle>
          </CardHeader>
          <CardContent>
            {o.invoice_id ? (
              <OrderInvoice invoiceId={o.invoice_id} />
            ) : (
              <p className="text-sm text-muted-foreground">
                {o.posted ? "Not invoiced yet." : "Not worked yet."}
              </p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
