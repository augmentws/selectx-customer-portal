"use client";

import { ArrowDown, ArrowUp, Search } from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useState } from "react";

import { formatPestPacDate } from "@/components/service-order-list";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { errorMessage } from "@/lib/api/errors";
import type { LocationRead } from "@/lib/api/generated/model";

const PAGE_SIZE = 50;

type QueryState<T> = {
  isPending: boolean;
  isError: boolean;
  error: unknown;
  data?: { data: T[] };
};

type SortKey = "name" | "place" | "open" | "worked" | "last";
type Sort = { key: SortKey; desc: boolean };

/** Orders PestPac lists that haven't been worked yet (the API's open count includes worked). */
const worked = (l: LocationRead) => l.worked_order_count ?? 0;
const scheduled = (l: LocationRead) => (l.open_order_count ?? 0) - worked(l);

const place = (l: LocationRead) => [l.city, l.state].filter(Boolean).join(", ");

const SORT_VALUE: Record<SortKey, (l: LocationRead) => string | number> = {
  name: (l) => (l.pestpac_company ?? "").toLowerCase(),
  place: (l) => place(l).toLowerCase(),
  open: scheduled,
  worked,
  last: (l) => l.last_service_at ?? "",
};

/** Name, store number, street, city, state, zip, and bill-to (when shown), lower-cased for
 * type-ahead matching. */
function searchText(location: LocationRead, billTo: string | undefined): string {
  return [
    location.pestpac_company,
    billTo,
    location.pestpac_location_code,
    String(location.pestpac_location_id),
    location.address,
    location.address2,
    location.city,
    location.state,
    location.zip,
  ]
    .filter(Boolean)
    .join(" ")
    .toLowerCase();
}

function sorted(list: LocationRead[], sort: Sort): LocationRead[] {
  const value = SORT_VALUE[sort.key];
  const dir = sort.desc ? -1 : 1;
  // Locations no longer under the bill-to stay at the end whatever the sort.
  return [...list].sort((a, b) => {
    const removed = Number(a.removed_at !== null) - Number(b.removed_at !== null);
    if (removed !== 0) return removed;
    const [x, y] = [value(a), value(b)];
    return x < y ? -dir : x > y ? dir : 0;
  });
}

function SortHeader({
  label,
  column,
  sort,
  onSort,
  className,
}: {
  label: string;
  column: SortKey;
  sort: Sort;
  onSort: (key: SortKey) => void;
  className?: string;
}) {
  const active = sort.key === column;
  const Arrow = sort.desc ? ArrowDown : ArrowUp;
  return (
    <th
      scope="col"
      aria-sort={active ? (sort.desc ? "descending" : "ascending") : "none"}
      className={className}
    >
      <button
        type="button"
        onClick={() => onSort(column)}
        className="inline-flex items-center gap-1 font-medium hover:text-foreground"
      >
        {label}
        {active && <Arrow aria-hidden className="size-3.5" />}
      </button>
    </th>
  );
}

function LocationRow({ location: l, billTo }: { location: LocationRead; billTo?: string }) {
  const removed = l.removed_at !== null;
  const open = scheduled(l);
  return (
    <tr className={removed ? "text-muted-foreground" : undefined}>
      <td className="py-2 pr-3">
        <Link href={`/locations/${l.id}`} className="font-medium text-primary hover:underline">
          {l.pestpac_company ?? `LocationID ${l.pestpac_location_id}`}
        </Link>
        {removed && (
          <Badge variant="outline" className="ml-2">
            No longer under this bill-to
          </Badge>
        )}
        {!removed && !l.pestpac_active && (
          <Badge variant="warning" className="ml-2">
            Inactive in PestPac
          </Badge>
        )}
        <div className="text-xs text-muted-foreground">
          <span className="sm:hidden">{place(l) && `${place(l)} · `}</span>
          LocationID {l.pestpac_location_id}
          {billTo && ` · Bill-to: ${billTo}`}
        </div>
      </td>
      <td className="hidden py-2 pr-3 sm:table-cell">{place(l)}</td>
      <td className="py-2 pr-3 text-right tabular-nums">{open || "—"}</td>
      <td className="py-2 pr-3 text-right tabular-nums">{worked(l) || "—"}</td>
      <td className="hidden py-2 text-right whitespace-nowrap sm:table-cell">
        {l.last_service_at ? formatPestPacDate(l.last_service_at) : "—"}
      </td>
    </tr>
  );
}

/**
 * Locations as a table: open and worked order counts and the last service, sortable by column,
 * filtered as you type, 50 rows at a time. Each opens its location page.
 */
export function LocationsTable({
  locations,
  billTos,
  emptyText = "PestPac lists no locations under this bill-to.",
}: {
  locations: QueryState<LocationRead>;
  /** Bill-to names by id: each row then names its bill-to (for lists spanning several). */
  billTos?: Map<string, string>;
  emptyText?: string;
}) {
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);
  const [sort, setSort] = useState<Sort>({ key: "name", desc: false });
  const [page, setPage] = useState(0);

  if (locations.isPending) return <p className="text-muted-foreground">Loading…</p>;
  if (locations.isError || !locations.data) {
    return (
      <Alert variant="destructive">
        <AlertDescription>
          {errorMessage(locations.error, "Could not load locations.")}
        </AlertDescription>
      </Alert>
    );
  }
  const all = locations.data.data;
  const terms = deferredQuery.toLowerCase().split(/\s+/).filter(Boolean);
  const matching =
    terms.length === 0
      ? all
      : all.filter((l) => {
          const text = searchText(l, billTos?.get(l.bill_to_id));
          return terms.every((t) => text.includes(t));
        });
  const rows = sorted(matching, sort);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const current = Math.min(page, pages - 1);
  const visible = rows.slice(current * PAGE_SIZE, (current + 1) * PAGE_SIZE);

  // Counts read best largest first; names and places A to Z.
  const onSort = (key: SortKey) => {
    setSort((s) =>
      s.key === key ? { key, desc: !s.desc } : { key, desc: key !== "name" && key !== "place" },
    );
    setPage(0);
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-md">
          <Search
            className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            type="search"
            aria-label="Filter locations"
            placeholder="Filter by name, store number, address, or state"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(0);
            }}
            className="pl-8"
          />
        </div>
        <p className="text-sm text-muted-foreground" aria-live="polite">
          {terms.length > 0
            ? `${matching.length} of ${all.length} locations`
            : `${all.length} locations`}
        </p>
      </div>

      {all.length === 0 ? (
        <p className="border border-border bg-card p-4 text-muted-foreground">{emptyText}</p>
      ) : matching.length === 0 ? (
        <p className="border border-border bg-card p-4 text-muted-foreground">
          No locations match “{deferredQuery}”.
        </p>
      ) : (
        <div className="border border-border bg-card px-4">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-border text-xs text-muted-foreground">
              <tr>
                <SortHeader
                  label="Location"
                  column="name"
                  sort={sort}
                  onSort={onSort}
                  className="py-2 pr-3"
                />
                <SortHeader
                  label="City"
                  column="place"
                  sort={sort}
                  onSort={onSort}
                  className="hidden py-2 pr-3 sm:table-cell"
                />
                <SortHeader
                  label="Open"
                  column="open"
                  sort={sort}
                  onSort={onSort}
                  className="py-2 pr-3 text-right"
                />
                <SortHeader
                  label="Worked"
                  column="worked"
                  sort={sort}
                  onSort={onSort}
                  className="py-2 pr-3 text-right"
                />
                <SortHeader
                  label="Last service"
                  column="last"
                  sort={sort}
                  onSort={onSort}
                  className="hidden py-2 text-right sm:table-cell"
                />
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {visible.map((location) => (
                <LocationRow
                  key={location.id}
                  location={location}
                  billTo={billTos?.get(location.bill_to_id)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {pages > 1 && (
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
          <span className="text-muted-foreground">
            {current * PAGE_SIZE + 1}–{current * PAGE_SIZE + visible.length} of {rows.length}
          </span>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={current === 0}
              onClick={() => setPage(current - 1)}
            >
              Previous
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={current >= pages - 1}
              onClick={() => setPage(current + 1)}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
