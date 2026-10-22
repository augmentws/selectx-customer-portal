"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useMemo, useState } from "react";

import { BillToDetailLines } from "@/components/bill-to-onboarding";
import { LocationSyncResult } from "@/components/location-sync-result";
import {
  type OrderStatusFilter,
  OrderStatusSelect,
  ServiceOrderList,
} from "@/components/service-order-list";
import { SyncJobPanel } from "@/components/sync-job-panel";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { errorMessage } from "@/lib/api/errors";
import {
  getBillTosGetBillToQueryKey,
  getBillTosListLocationsQueryKey,
  getBillTosListServiceOrdersQueryKey,
  useBillTosGetBillTo,
  useBillTosListLocations,
  useBillTosListServiceOrders,
  useBillTosRefreshBillTo,
} from "@/lib/api/generated/bill-tos/bill-tos";
import type { LocationRead } from "@/lib/api/generated/model";
import { usePermissions } from "@/lib/permissions";

function LocationRow({ location }: { location: LocationRead }) {
  const removed = location.removed_at !== null;
  const street = [location.address, location.address2].filter(Boolean).join(", ");
  const place = [location.city, [location.state, location.zip].filter(Boolean).join(" ")]
    .filter(Boolean)
    .join(", ");
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
    </li>
  );
}

export function BillToDetail() {
  const { billToId } = useParams<{ billToId: string }>();
  const queryClient = useQueryClient();
  const { can } = usePermissions();
  const billTo = useBillTosGetBillTo(billToId);
  const locations = useBillTosListLocations(billToId);
  const [status, setStatus] = useState<OrderStatusFilter>("open");
  const orders = useBillTosListServiceOrders(billToId, { status });
  const locationNames = useMemo(
    () =>
      new Map(
        (locations.data?.data ?? []).map((l) => [l.id, l.pestpac_company ?? "Unnamed location"]),
      ),
    [locations.data],
  );
  const onSynced = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: getBillTosListServiceOrdersQueryKey(billToId) });
    queryClient.invalidateQueries({ queryKey: getBillTosListLocationsQueryKey(billToId) });
  }, [queryClient, billToId]);
  const refresh = useBillTosRefreshBillTo({
    mutation: {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getBillTosGetBillToQueryKey(billToId) });
        queryClient.invalidateQueries({ queryKey: getBillTosListLocationsQueryKey(billToId) });
      },
    },
  });

  if (billTo.isPending) return <p className="text-muted-foreground">Loading…</p>;
  if (billTo.isError) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{errorMessage(billTo.error, "Bill-to not found.")}</AlertDescription>
      </Alert>
    );
  }
  const b = billTo.data.data;
  const canWrite = can("bill_tos:write", b.operator_id);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Link
          href={`/companies/${b.company_id}`}
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          ← Company
        </Link>
        <h1 className="mt-2 flex flex-wrap items-center gap-3 text-3xl">
          {b.name}
          {!b.is_active && <Badge variant="outline">Inactive</Badge>}
        </h1>
        <p className="text-muted-foreground">
          BillToID {b.pestpac_bill_to_id}
          {b.description && ` · ${b.description}`}
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>PestPac details</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <BillToDetailLines details={b} />
          <p className="text-xs text-muted-foreground">
            {b.pestpac_fetched_at
              ? `From PestPac ${new Date(b.pestpac_fetched_at).toLocaleString()}`
              : "Not fetched from PestPac yet."}
          </p>
          {canWrite && (
            <div>
              <Button
                variant="outline"
                disabled={refresh.isPending}
                onClick={() => refresh.mutate({ billToId })}
              >
                {refresh.isPending ? "Refreshing…" : "Refresh from PestPac"}
              </Button>
            </div>
          )}
          {refresh.isSuccess && (
            <LocationSyncResult summary={refresh.data.data.locations_sync} label="Refreshed" />
          )}
          {refresh.isError && (
            <Alert variant="destructive">
              <AlertDescription>{errorMessage(refresh.error)}</AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-xl">Service orders</h2>
          <OrderStatusSelect value={status} onChange={setStatus} />
        </div>
        <SyncJobPanel billToId={billToId} canSync={canWrite && b.is_active} onFinished={onSynced} />
        <ServiceOrderList query={orders} status={status} locationNames={locationNames} />
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-xl">Locations ({b.location_count})</h2>
        {locations.isPending && <p className="text-muted-foreground">Loading…</p>}
        {locations.isError && (
          <Alert variant="destructive">
            <AlertDescription>
              {errorMessage(locations.error, "Could not load locations.")}
            </AlertDescription>
          </Alert>
        )}
        {locations.data && (
          <ul className="divide-y divide-border border border-border bg-card">
            {locations.data.data.length === 0 && (
              <li className="p-4 text-muted-foreground">
                PestPac lists no locations under this bill-to.
              </li>
            )}
            {locations.data.data.map((location) => (
              <LocationRow key={location.id} location={location} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
