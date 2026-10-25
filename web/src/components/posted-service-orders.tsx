"use client";

import { keepPreviousData } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useEffect, useState } from "react";

import { ReportAction, useServiceReportTemplates } from "@/components/report-action";
import { OrderRow } from "@/components/service-order-list";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { errorMessage } from "@/lib/api/errors";
import { useBillTosListPostedServiceOrders } from "@/lib/api/generated/bill-tos/bill-tos";
import { useCompaniesListPostedServiceOrders } from "@/lib/api/generated/companies/companies";
import type { PostedServiceOrderPage, ReportTemplateRead } from "@/lib/api/generated/model";
import { useUrlParams } from "@/lib/use-url-params";

const PAGE_SIZE = 50;
const DEBOUNCE_MS = 300;
const PARAMS = ["q", "tech", "code", "offset"] as const;

type PageQuery = {
  isPending: boolean;
  isError: boolean;
  error: unknown;
  data?: { data: PostedServiceOrderPage };
};

/** Search box, technician, and service code, kept in the URL. */
function Filters({
  page,
  values,
  set,
}: {
  page: PostedServiceOrderPage | undefined;
  values: Record<(typeof PARAMS)[number], string>;
  set: (changes: Partial<Record<(typeof PARAMS)[number], string>>) => void;
}) {
  const [input, setInput] = useState(values.q);
  useEffect(() => {
    if (input.trim() === values.q) return;
    const t = setTimeout(() => set({ q: input.trim(), offset: "" }), DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [input, values.q, set]);

  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="relative w-full max-w-xs">
        <Search
          className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <Input
          type="search"
          aria-label="Search orders"
          placeholder="Store or order number"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          className="pl-8"
        />
      </div>
      <NativeSelect
        size="sm"
        aria-label="Technician"
        value={values.tech}
        onChange={(e) => set({ tech: e.target.value, offset: "" })}
      >
        <NativeSelectOption value="">All technicians</NativeSelectOption>
        {page?.technicians.map((t) => (
          <NativeSelectOption key={t.id} value={t.id}>
            {t.name}
          </NativeSelectOption>
        ))}
      </NativeSelect>
      <NativeSelect
        size="sm"
        aria-label="Service code"
        value={values.code}
        onChange={(e) => set({ code: e.target.value, offset: "" })}
      >
        <NativeSelectOption value="">All services</NativeSelectOption>
        {page?.service_codes.map((code) => (
          <NativeSelectOption key={code} value={code}>
            {code}
          </NativeSelectOption>
        ))}
      </NativeSelect>
      {(values.q || values.tech || values.code) && (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            setInput("");
            set({ q: "", tech: "", code: "", offset: "" });
          }}
        >
          Clear filters
        </Button>
      )}
    </div>
  );
}

function OrderList({
  query,
  offset,
  setOffset,
  filtered,
  templates,
}: {
  query: PageQuery;
  offset: number;
  setOffset: (offset: number) => void;
  filtered: boolean;
  templates: ReportTemplateRead[];
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
          <li className="p-4 text-muted-foreground">
            {filtered
              ? "No worked orders match these filters."
              : "No worked orders waiting for an invoice."}
          </li>
        )}
        {page.items.map((order) => (
          <OrderRow
            key={order.id}
            order={order}
            compact
            locationName={order.location_name ?? undefined}
            actions={
              <ReportAction
                orderId={order.id}
                locationId={order.location_id}
                reportId={order.report_id}
                templates={templates}
              />
            }
          />
        ))}
      </ul>
      {page.total > PAGE_SIZE && (
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

/** Worked orders without an invoice for a bill-to or a whole company, oldest first, filtered
 * by store or order number, technician, and service code. */
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
  const [values, set] = useUrlParams(PARAMS);
  const offset = Number(values.offset) || 0;
  const templates = useServiceReportTemplates(companyId, operatorId);
  const params = {
    limit: PAGE_SIZE,
    offset,
    ...(values.q && { q: values.q }),
    ...(values.tech && { technician_id: values.tech }),
    ...(values.code && { service_code: values.code }),
  };
  const isBillTo = billToId !== undefined;
  const billTo = useBillTosListPostedServiceOrders(billToId ?? "", params, {
    query: { enabled: isBillTo, placeholderData: keepPreviousData },
  });
  const company = useCompaniesListPostedServiceOrders(companyId, params, {
    query: { enabled: !isBillTo, placeholderData: keepPreviousData },
  });
  const query = isBillTo ? billTo : company;
  const page = query.data?.data;
  const filtered = Boolean(values.q || values.tech || values.code);

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground" aria-live="polite">
        {page
          ? `${page.total} worked ${page.total === 1 ? "order" : "orders"} ${
              filtered ? (page.total === 1 ? "matches" : "match") : "awaiting an invoice"
            }, oldest first. Invoiced ones are under Invoiced orders.`
          : "Worked orders awaiting an invoice, oldest first."}
      </p>
      <Filters page={page} values={values} set={set} />
      <OrderList
        query={query}
        offset={offset}
        setOffset={(next) => set({ offset: next ? String(next) : "" })}
        filtered={filtered}
        templates={templates}
      />
    </div>
  );
}
