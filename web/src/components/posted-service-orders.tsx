"use client";

import { keepPreviousData } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { ReportAction, useServiceReportTemplates } from "@/components/report-action";
import { OrderRow } from "@/components/service-order-list";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { errorMessage } from "@/lib/api/errors";
import {
  useBillTosListOpenServiceOrders,
  useBillTosListPostedServiceOrders,
} from "@/lib/api/generated/bill-tos/bill-tos";
import {
  useCompaniesListOpenServiceOrders,
  useCompaniesListPostedServiceOrders,
} from "@/lib/api/generated/companies/companies";
import type { PostedServiceOrderPage, ReportTemplateRead } from "@/lib/api/generated/model";
import { useUrlParams } from "@/lib/use-url-params";

const PAGE_SIZE = 50;
const DEBOUNCE_MS = 300;
const KEYS = ["q", "tech", "code", "sort", "offset"] as const;
type Key = (typeof KEYS)[number];
type Values = Record<Key, string>;
// The open-orders tab keeps its own filters, so switching tabs doesn't carry them over.
const URL_KEYS = {
  posted: { q: "q", tech: "tech", code: "code", sort: "sort", offset: "offset" },
  open: { q: "oq", tech: "otech", code: "ocode", sort: "osort", offset: "ooffset" },
} as const;

/** This list's filters, read from and written to its own URL parameters. */
function useListParams(kind: "posted" | "open"): [Values, (changes: Partial<Values>) => void] {
  const names = URL_KEYS[kind];
  const [raw, setRaw] = useUrlParams(Object.values(names));
  const values = Object.fromEntries(KEYS.map((k) => [k, raw[names[k]]])) as Values;
  const set = useCallback(
    (changes: Partial<Values>) =>
      setRaw(
        Object.fromEntries(
          Object.entries(changes).map(([k, v]) => [names[k as Key], v]),
        ) as Partial<Record<(typeof names)[Key], string>>,
      ),
    [names, setRaw],
  );
  return [values, set];
}

type PageQuery = {
  isPending: boolean;
  isError: boolean;
  error: unknown;
  data?: { data: PostedServiceOrderPage };
};

/** Search box, technician, service code, and date order, kept in the URL. */
function Filters({
  page,
  values,
  set,
}: {
  page: PostedServiceOrderPage | undefined;
  values: Values;
  set: (changes: Partial<Values>) => void;
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
      <NativeSelect
        size="sm"
        aria-label="Date order"
        value={values.sort}
        onChange={(e) => set({ sort: e.target.value, offset: "" })}
      >
        <NativeSelectOption value="">Oldest first</NativeSelectOption>
        <NativeSelectOption value="desc">Newest first</NativeSelectOption>
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
  kind,
  query,
  offset,
  setOffset,
  newestFirst,
  filtered,
  templates,
}: {
  kind: "posted" | "open";
  query: PageQuery;
  offset: number;
  setOffset: (offset: number) => void;
  newestFirst: boolean;
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
              ? `No ${kind === "open" ? "open" : "worked"} orders match these filters.`
              : kind === "open"
                ? "No open orders."
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
              kind === "posted" && (
                <ReportAction
                  orderId={order.id}
                  locationId={order.location_id}
                  reportId={order.report_id}
                  templates={templates}
                />
              )
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
              {newestFirst ? "Newer" : "Older"}
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={page.offset + page.items.length >= page.total}
              onClick={() => setOffset(offset + PAGE_SIZE)}
            >
              {newestFirst ? "Older" : "Newer"}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

/** Summary above the list: how many orders, in which order. */
function summary(
  kind: "posted" | "open",
  page: PostedServiceOrderPage | undefined,
  filtered: boolean,
  order: string,
): string {
  if (kind === "open") {
    if (!page) return `Orders not worked yet, ${order}.`;
    const noun = page.total === 1 ? "order" : "orders";
    return filtered
      ? `${page.total} open ${noun} ${page.total === 1 ? "matches" : "match"}, ${order}.`
      : `${page.total} open ${noun} not worked yet, ${order}. Worked ones are under Posted service orders.`;
  }
  if (!page) return `Worked orders awaiting an invoice, ${order}.`;
  return `${page.total} worked ${page.total === 1 ? "order" : "orders"} ${
    filtered ? (page.total === 1 ? "matches" : "match") : "awaiting an invoice"
  }, ${order}. Invoiced ones are under Invoiced orders.`;
}

/** Service orders for a bill-to or a whole company, filtered by store or order number,
 * technician, and service code, by work date (oldest first unless chosen otherwise).
 * `posted`: worked orders without an invoice, each with its report action. `open`: orders not
 * worked yet. */
export function PostedServiceOrders({
  kind = "posted",
  billToId,
  companyId,
  operatorId,
}: {
  kind?: "posted" | "open";
  /** Only this bill-to's orders; otherwise the whole company's. */
  billToId?: string;
  companyId: string;
  operatorId: string;
}) {
  const [values, set] = useListParams(kind);
  const offset = Number(values.offset) || 0;
  const newestFirst = values.sort === "desc";
  const templates = useServiceReportTemplates(companyId, operatorId);
  const params = {
    limit: PAGE_SIZE,
    offset,
    ...(values.q && { q: values.q }),
    ...(values.tech && { technician_id: values.tech }),
    ...(values.code && { service_code: values.code }),
    ...(newestFirst && { sort: "desc" as const }),
  };
  const isBillTo = billToId !== undefined;
  const isOpen = kind === "open";
  const options = (enabled: boolean) => ({
    query: { enabled, placeholderData: keepPreviousData },
  });
  const billToPosted = useBillTosListPostedServiceOrders(
    billToId ?? "",
    params,
    options(isBillTo && !isOpen),
  );
  const companyPosted = useCompaniesListPostedServiceOrders(
    companyId,
    params,
    options(!isBillTo && !isOpen),
  );
  const billToOpen = useBillTosListOpenServiceOrders(
    billToId ?? "",
    params,
    options(isBillTo && isOpen),
  );
  const companyOpen = useCompaniesListOpenServiceOrders(
    companyId,
    params,
    options(!isBillTo && isOpen),
  );
  const query = isOpen
    ? isBillTo
      ? billToOpen
      : companyOpen
    : isBillTo
      ? billToPosted
      : companyPosted;
  const page = query.data?.data;
  const filtered = Boolean(values.q || values.tech || values.code);

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground" aria-live="polite">
        {summary(kind, page, filtered, newestFirst ? "newest first" : "oldest first")}
      </p>
      <Filters page={page} values={values} set={set} />
      <OrderList
        kind={kind}
        newestFirst={newestFirst}
        query={query}
        offset={offset}
        setOffset={(next) => set({ offset: next ? String(next) : "" })}
        filtered={filtered}
        templates={templates}
      />
    </div>
  );
}
