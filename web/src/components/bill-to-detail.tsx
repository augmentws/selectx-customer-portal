"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useState } from "react";

import { BillToLocations } from "@/components/bill-to-locations";
import { BillToDetailLines } from "@/components/bill-to-onboarding";
import { LocationSyncResult } from "@/components/location-sync-result";
import { type OrderStatusFilter, OrderStatusSelect } from "@/components/service-order-list";
import { SyncJobPanel } from "@/components/sync-job-panel";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { errorMessage } from "@/lib/api/errors";
import {
  getBillTosGetBillToQueryKey,
  getBillTosListLocationsQueryKey,
  useBillTosGetBillTo,
  useBillTosListLocations,
  useBillTosRefreshBillTo,
} from "@/lib/api/generated/bill-tos/bill-tos";
import { usePermissions } from "@/lib/permissions";

export function BillToDetail() {
  const { billToId } = useParams<{ billToId: string }>();
  const queryClient = useQueryClient();
  const { can } = usePermissions();
  const billTo = useBillTosGetBillTo(billToId);
  const locations = useBillTosListLocations(billToId);
  const [status, setStatus] = useState<OrderStatusFilter>("open");
  const onSynced = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: getBillTosListLocationsQueryKey(billToId) });
    // Expanded locations' orders (keys are `/v1/locations/{id}/service-orders`).
    queryClient.invalidateQueries({
      predicate: (q) => String(q.queryKey[0]).endsWith("/service-orders"),
    });
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
          <h2 className="text-xl">Locations and service orders</h2>
          <OrderStatusSelect value={status} onChange={setStatus} />
        </div>
        <SyncJobPanel billToId={billToId} canSync={canWrite && b.is_active} onFinished={onSynced} />
        <BillToLocations locations={locations} status={status} />
      </section>
    </div>
  );
}
