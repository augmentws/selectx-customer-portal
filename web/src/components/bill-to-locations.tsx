"use client";

import { ChevronDown, ChevronRight, Search } from "lucide-react";
import Link from "next/link";
import { useDeferredValue, useState } from "react";

import { type OrderStatusFilter, OrderRow } from "@/components/service-order-list";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { errorMessage } from "@/lib/api/errors";
import { useLocationsListServiceOrders } from "@/lib/api/generated/locations/locations";
import type { LocationRead } from "@/lib/api/generated/model";

const NO_ORDERS: Record<OrderStatusFilter, string> = {
  open: "No open or worked orders.",
  closed: "No billed orders recorded yet.",
  all: "No orders recorded yet.",
};

type QueryState<T> = {
  isPending: boolean;
  isError: boolean;
  error: unknown;
  data?: { data: T[] };
};

/** Name, street, city, state, and zip, lower-cased for type-ahead matching. */
function searchText(location: LocationRead): string {
  return [
    location.pestpac_company,
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

/** Fetched only while the location is expanded, so a large bill-to loads one location at a time. */
function LocationOrders({ locationId, status }: { locationId: string; status: OrderStatusFilter }) {
  const orders = useLocationsListServiceOrders(locationId, { status });
  if (orders.isPending) return <p className="p-4 text-sm text-muted-foreground">Loading orders…</p>;
  if (orders.isError) {
    return (
      <p className="p-4 text-sm text-destructive">
        {errorMessage(orders.error, "Could not load service orders.")}
      </p>
    );
  }
  if (orders.data.data.length === 0) {
    return <p className="p-4 text-sm text-muted-foreground">{NO_ORDERS[status]}</p>;
  }
  return (
    <ul className="divide-y divide-border">
      {orders.data.data.map((order) => (
        <OrderRow key={order.id} order={order} showLocation={false} />
      ))}
    </ul>
  );
}

function LocationGroup({
  location,
  status,
}: {
  location: LocationRead;
  status: OrderStatusFilter;
}) {
  const [expanded, setExpanded] = useState(false);
  const removed = location.removed_at !== null;
  const street = [location.address, location.address2].filter(Boolean).join(", ");
  const place = [location.city, [location.state, location.zip].filter(Boolean).join(" ")]
    .filter(Boolean)
    .join(", ");
  const panelId = `orders-${location.id}`;
  return (
    <li className={removed ? "p-4 text-muted-foreground" : "p-4"}>
      <div className="flex flex-wrap items-center gap-2">
        <Link
          href={`/locations/${location.id}`}
          className="font-medium text-primary hover:underline"
        >
          {location.pestpac_company ?? "Unnamed location"}
        </Link>
        {(location.open_order_count ?? 0) > 0 && (
          <Badge variant="secondary">
            {location.open_order_count} open {location.open_order_count === 1 ? "order" : "orders"}
          </Badge>
        )}
        <span className="text-sm text-muted-foreground">
          LocationID {location.pestpac_location_id}
          {location.pestpac_location_code && ` · code ${location.pestpac_location_code}`}
        </span>
        {removed && <Badge variant="outline">No longer under this bill-to</Badge>}
        {!removed && !location.pestpac_active && (
          <Badge variant="warning">Inactive in PestPac</Badge>
        )}
      </div>
      <div className="mt-1 grid gap-x-6 text-sm sm:grid-cols-3">
        <span>
          {street}
          {street && place && <br />}
          {place}
        </span>
        <span>
          {location.phone}
          {location.phone && location.email && <br />}
          {location.email && (
            <a href={`mailto:${location.email}`} className="text-primary hover:underline">
              {location.email}
            </a>
          )}
        </span>
        <span className="text-muted-foreground">
          {[location.account_type, location.pestpac_type].filter(Boolean).join(" · ")}
        </span>
      </div>
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={panelId}
        onClick={() => setExpanded((v) => !v)}
        className="mt-2 inline-flex items-center gap-1 text-sm text-primary hover:underline"
      >
        {expanded ? (
          <ChevronDown className="size-4" aria-hidden />
        ) : (
          <ChevronRight className="size-4" aria-hidden />
        )}
        {expanded ? "Hide orders" : "Show orders"}
      </button>
      {expanded && (
        <div id={panelId} className="mt-2 border-l-2 border-border text-foreground">
          <LocationOrders locationId={location.id} status={status} />
        </div>
      )}
    </li>
  );
}

/**
 * A bill-to's locations in the API's order (current first, by name), filtered as you type. Each
 * expands to its own service orders for the selected status.
 */
export function BillToLocations({
  locations,
  status,
}: {
  locations: QueryState<LocationRead>;
  status: OrderStatusFilter;
}) {
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query);

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
  const visible =
    terms.length === 0
      ? all
      : all.filter((l) => {
          const text = searchText(l);
          return terms.every((t) => text.includes(t));
        });

  return (
    <div className="flex flex-col gap-3">
      <div className="relative max-w-md">
        <Search
          className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <Input
          type="search"
          aria-label="Filter locations"
          placeholder="Filter by name, address, or state"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="pl-8"
        />
      </div>
      <p className="text-sm text-muted-foreground" aria-live="polite">
        {terms.length > 0
          ? `${visible.length} of ${all.length} locations`
          : `${all.length} locations`}
      </p>
      <ul className="divide-y divide-border border border-border bg-card">
        {all.length === 0 && (
          <li className="p-4 text-muted-foreground">
            PestPac lists no locations under this bill-to.
          </li>
        )}
        {all.length > 0 && visible.length === 0 && (
          <li className="p-4 text-muted-foreground">No locations match “{deferredQuery}”.</li>
        )}
        {visible.map((location) => (
          <LocationGroup key={location.id} location={location} status={status} />
        ))}
      </ul>
    </div>
  );
}
