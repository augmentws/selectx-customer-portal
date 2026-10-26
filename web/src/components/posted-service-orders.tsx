"use client";

import { keepPreviousData, useQuery, type UseQueryOptions } from "@tanstack/react-query";
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
  getBillTosListOpenServiceOrdersQueryOptions,
  getBillTosListPostedServiceOrdersQueryOptions,
} from "@/lib/api/generated/bill-tos/bill-tos";
import {
  getCompaniesListOpenServiceOrdersQueryOptions,
  getCompaniesListPostedServiceOrdersQueryOptions,
} from "@/lib/api/generated/companies/companies";
import {
  getLocationsListInvoicedServiceOrdersQueryOptions,
  getLocationsListOpenServiceOrdersQueryOptions,
  getLocationsListPostedServiceOrdersQueryOptions,
} from "@/lib/api/generated/locations/locations";
import type { PostedServiceOrderPage, ReportTemplateRead } from "@/lib/api/generated/model";
import { useUrlParams } from "@/lib/use-url-params";

const PAGE_SIZE = 50;
const DEBOUNCE_MS = 300;
const KEYS = ["q", "tech", "code", "sort", "offset"] as const;
type Key = (typeof KEYS)[number];
type Values = Record<Key, string>;
/** `posted`: worked, without an invoice. `invoiced`: with one (a location's orders only; bill-tos
 * and companies list invoices instead). `open`: not worked yet. */
export type OrderListKind = "posted" | "invoiced" | "open";
// Each list keeps its own filters, so switching tabs doesn't carry them over.
const URL_KEYS = {
  posted: { q: "q", tech: "tech", code: "code", sort: "sort", offset: "offset" },
  invoiced: { q: "iq", tech: "itech", code: "icode", sort: "isort", offset: "ioffset" },
  open: { q: "oq", tech: "otech", code: "ocode", sort: "osort", offset: "ooffset" },
} as const;

/** This list's filters, read from and written to its own URL parameters. */
function useListParams(kind: OrderListKind): [Values, (changes: Partial<Values>) => void] {
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
  placeholder,
}: {
  placeholder: string;
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
          placeholder={placeholder}
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
  showLocation,
}: {
  kind: OrderListKind;
  showLocation: boolean;
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
              ? `No ${kind === "posted" ? "worked" : kind} orders match these filters.`
              : EMPTY[kind]}
          </li>
        )}
        {page.items.map((order) => (
          <OrderRow
            key={order.id}
            order={order}
            compact
            showLocation={showLocation}
            locationName={order.location_name ?? undefined}
            actions={
              kind !== "open" && (
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

const EMPTY: Record<OrderListKind, string> = {
  posted: "No worked orders waiting for an invoice.",
  invoiced: "No invoiced orders yet.",
  open: "No open orders.",
};

const NOUN: Record<OrderListKind, string> = {
  posted: "worked",
  invoiced: "invoiced",
  open: "open",
};

/** Summary above the list: how many orders, in which order, and (on bill-to and company
 * pages) where the others are. */
function summary(
  kind: OrderListKind,
  page: PostedServiceOrderPage | undefined,
  filtered: boolean,
  order: string,
  hints: boolean,
): string {
  if (!page) return `${EMPTY_LOADING[kind]}, ${order}.`;
  const noun = page.total === 1 ? "order" : "orders";
  const what = filtered
    ? page.total === 1
      ? " matches"
      : " match"
    : { posted: " awaiting an invoice", invoiced: "", open: " not worked yet" }[kind];
  const hint = !hints
    ? ""
    : kind === "posted"
      ? " Invoiced ones are under Invoiced orders."
      : kind === "open"
        ? " Worked ones are under Posted service orders."
        : "";
  return `${page.total} ${NOUN[kind]} ${noun}${what}, ${order}.${hint}`;
}

const EMPTY_LOADING: Record<OrderListKind, string> = {
  posted: "Worked orders awaiting an invoice",
  invoiced: "Orders with an invoice",
  open: "Orders not worked yet",
};

type OrderScope = { billToId: string } | { companyId: string } | { locationId: string };
type PageResponse = { data: PostedServiceOrderPage };

/** The query for this list and scope (bill-tos and companies have no `invoiced` list). */
function listQuery(
  kind: OrderListKind,
  scope: OrderScope,
  params: Parameters<typeof getLocationsListPostedServiceOrdersQueryOptions>[1],
): UseQueryOptions<PageResponse> {
  if ("locationId" in scope) {
    const get = {
      posted: getLocationsListPostedServiceOrdersQueryOptions,
      invoiced: getLocationsListInvoicedServiceOrdersQueryOptions,
      open: getLocationsListOpenServiceOrdersQueryOptions,
    }[kind];
    return get(scope.locationId, params) as UseQueryOptions<PageResponse>;
  }
  if (kind === "invoiced") {
    throw new Error("Invoiced orders are listed per location only");
  }
  if ("billToId" in scope) {
    const get = {
      posted: getBillTosListPostedServiceOrdersQueryOptions,
      open: getBillTosListOpenServiceOrdersQueryOptions,
    }[kind];
    return get(scope.billToId, params) as UseQueryOptions<PageResponse>;
  }
  const get = {
    posted: getCompaniesListPostedServiceOrdersQueryOptions,
    open: getCompaniesListOpenServiceOrdersQueryOptions,
  }[kind];
  return get(scope.companyId, params) as UseQueryOptions<PageResponse>;
}

/** Service orders for a location, a bill-to, or a whole company, filtered by store or order
 * number, technician, and service code, by work date (oldest first unless chosen otherwise).
 * See `OrderListKind`; worked ones (posted and invoiced) carry their report action. */
export function PostedServiceOrders({
  kind = "posted",
  locationId,
  billToId,
  companyId,
  operatorId,
}: {
  kind?: OrderListKind;
  /** Only this location's orders. */
  locationId?: string;
  /** Only this bill-to's orders; otherwise the whole company's. */
  billToId?: string;
  /** The company whose report templates the report action offers. */
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
  const scope: OrderScope =
    locationId !== undefined
      ? { locationId }
      : billToId !== undefined
        ? { billToId }
        : { companyId };
  const query = useQuery({ ...listQuery(kind, scope, params), placeholderData: keepPreviousData });
  const page = query.data?.data;
  const filtered = Boolean(values.q || values.tech || values.code);

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground" aria-live="polite">
        {summary(
          kind,
          page,
          filtered,
          newestFirst ? "newest first" : "oldest first",
          locationId === undefined,
        )}
      </p>
      <Filters
        page={page}
        values={values}
        set={set}
        placeholder={locationId === undefined ? "Store or order number" : "Order number"}
      />
      <OrderList
        kind={kind}
        newestFirst={newestFirst}
        query={query}
        offset={offset}
        setOffset={(next) => set({ offset: next ? String(next) : "" })}
        filtered={filtered}
        templates={templates}
        showLocation={locationId === undefined}
      />
    </div>
  );
}
