"use client";

import { FileText } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { OrderRow } from "@/components/service-order-list";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { errorMessage } from "@/lib/api/errors";
import { useBillTosListPostedServiceOrders } from "@/lib/api/generated/bill-tos/bill-tos";
import { useCompaniesListPostedServiceOrders } from "@/lib/api/generated/companies/companies";
import type {
  PostedServiceOrderPage,
  PostedServiceOrderRead,
  ReportTemplateRead,
} from "@/lib/api/generated/model";
import {
  useReportsCreateServiceReport,
  useReportsListReportTemplates,
} from "@/lib/api/generated/reports/reports";
import { usePermissions } from "@/lib/permissions";

const PAGE_SIZE = 50;

/** Open the order's report, or start one (an order has one report). */
function ReportAction({
  order,
  templates,
}: {
  order: PostedServiceOrderRead;
  /** Service report templates the user may start from; empty: can't start. */
  templates: ReportTemplateRead[];
}) {
  const router = useRouter();
  const [templateId, setTemplateId] = useState("");
  const create = useReportsCreateServiceReport({
    mutation: { onSuccess: (res) => router.push(`/service-reports/${res.data.id}`) },
  });
  if (order.report_id) {
    return (
      <Link
        href={`/service-reports/${order.report_id}`}
        className={buttonVariants({ variant: "outline", size: "sm" })}
      >
        <FileText aria-hidden />
        Open report
      </Link>
    );
  }
  if (templates.length === 0 || !order.location_id) return null;
  const locationId = order.location_id;
  const chosen = templateId || templates[0].id;
  return (
    <>
      {templates.length > 1 && (
        <NativeSelect
          size="sm"
          aria-label="Report template"
          value={chosen}
          onChange={(e) => setTemplateId(e.target.value)}
        >
          {templates.map((t) => (
            <NativeSelectOption key={t.id} value={t.id}>
              {t.name}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      )}
      <Button
        size="sm"
        disabled={create.isPending}
        onClick={() =>
          create.mutate({ locationId, data: { template_id: chosen, service_order_id: order.id } })
        }
      >
        <FileText aria-hidden />
        {create.isPending ? "Starting…" : "Start report"}
      </Button>
      {create.isError && (
        <span className="text-sm text-destructive">{errorMessage(create.error)}</span>
      )}
    </>
  );
}

function PostedOrderPage({
  query,
  offset,
  setOffset,
  templates,
}: {
  templates: ReportTemplateRead[];
  query: {
    isPending: boolean;
    isError: boolean;
    error: unknown;
    data?: { data: PostedServiceOrderPage };
  };
  offset: number;
  setOffset: (offset: number) => void;
}) {
  if (query.isPending) return <p className="text-muted-foreground">Loading…</p>;
  if (query.isError || !query.data) {
    return (
      <Alert variant="destructive">
        <AlertDescription>
          {errorMessage(query.error, "Could not load service orders.")}
        </AlertDescription>
      </Alert>
    );
  }
  const page = query.data.data;
  return (
    <div className="flex flex-col gap-3">
      <ul className="divide-y divide-border border border-border bg-card">
        {page.items.length === 0 && (
          <li className="p-4 text-muted-foreground">No worked orders waiting for an invoice.</li>
        )}
        {page.items.map((order) => (
          <OrderRow
            key={order.id}
            order={order}
            locationName={order.location_name ?? undefined}
            actions={<ReportAction order={order} templates={templates} />}
          />
        ))}
      </ul>
      {page.total > 0 && (
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
          <span className="text-muted-foreground">
            {page.offset + 1}–{page.offset + page.items.length} of {page.total}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            >
              Older
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page.offset + page.items.length >= page.total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              Newer
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

/** Worked orders (billed or not) for a bill-to or a whole company, oldest first. */
export function PostedServiceOrders({
  billToId,
  companyId,
  operatorId,
}: {
  /** Only this bill-to's orders; otherwise the whole company's. */
  billToId?: string;
  companyId: string;
  operatorId: string;
}) {
  const [offset, setOffset] = useState(0);
  const { can } = usePermissions();
  const canStart = can("reports:write", operatorId);
  const allTemplates = useReportsListReportTemplates(companyId, undefined, {
    query: { enabled: canStart },
  });
  // Service reports need a template with report fields.
  const templates = canStart
    ? (allTemplates.data?.data.filter((t) => t.fields.length > 0) ?? [])
    : [];
  const params = { limit: PAGE_SIZE, offset };
  const isBillTo = billToId !== undefined;
  const billTo = useBillTosListPostedServiceOrders(billToId ?? "", params, {
    query: { enabled: isBillTo },
  });
  const company = useCompaniesListPostedServiceOrders(companyId, params, {
    query: { enabled: !isBillTo },
  });
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">
        Worked service orders without an invoice yet, oldest first. Invoiced ones are under Invoiced
        orders.
      </p>
      <PostedOrderPage
        query={isBillTo ? billTo : company}
        offset={offset}
        setOffset={setOffset}
        templates={templates}
      />
    </div>
  );
}
