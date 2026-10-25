"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useCallback, useState } from "react";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { LocationConditions } from "@/components/location-conditions";
import { LocationDocuments } from "@/components/location-documents";
import { LocationInvoices } from "@/components/location-invoices";
import { LocationServiceReports } from "@/components/location-service-reports";
import { NoteList } from "@/components/note-list";
import { LocationReports } from "@/components/report-templates";
import {
  type OrderStatusFilter,
  OrderStatusSelect,
  ServiceOrderList,
} from "@/components/service-order-list";
import { SyncJobPanel } from "@/components/sync-job-panel";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useDocumentTitle } from "@/lib/use-document-title";
import { errorMessage } from "@/lib/api/errors";
import { useBillTosGetBillTo } from "@/lib/api/generated/bill-tos/bill-tos";
import {
  getLocationsGetLocationQueryKey,
  getLocationsListConditionsQueryKey,
  getLocationsListDocumentsQueryKey,
  getLocationsListNotesQueryKey,
  getLocationsListServiceOrdersQueryKey,
  useLocationsGetLocation,
  useLocationsListNotes,
  useLocationsListServiceOrders,
} from "@/lib/api/generated/locations/locations";
import { usePermissions } from "@/lib/permissions";

export function LocationDetail() {
  const { locationId } = useParams<{ locationId: string }>();
  const queryClient = useQueryClient();
  const { can } = usePermissions();
  const [status, setStatus] = useState<OrderStatusFilter>("open");
  const location = useLocationsGetLocation(locationId);
  const billToId = location.data?.data.bill_to_id ?? "";
  const billTo = useBillTosGetBillTo(billToId, { query: { enabled: billToId !== "" } });
  const orders = useLocationsListServiceOrders(locationId, { status });
  const notes = useLocationsListNotes(locationId);
  const l = location.data?.data;
  useDocumentTitle(
    l && (l.pestpac_company ?? `LocationID ${l.pestpac_location_id}`),
    l?.trail.find((c) => c.kind === "company")?.name,
  );

  const onSynced = useCallback(() => {
    for (const queryKey of [
      getLocationsGetLocationQueryKey(locationId),
      getLocationsListServiceOrdersQueryKey(locationId),
      getLocationsListNotesQueryKey(locationId),
    ]) {
      queryClient.invalidateQueries({ queryKey });
    }
  }, [queryClient, locationId]);
  const onLocationSynced = useCallback(() => {
    for (const queryKey of [
      getLocationsListDocumentsQueryKey(locationId),
      getLocationsListConditionsQueryKey(locationId),
    ]) {
      queryClient.invalidateQueries({ queryKey });
    }
  }, [queryClient, locationId]);

  if (location.isPending) return <p className="text-muted-foreground">Loading…</p>;
  if (location.isError) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{errorMessage(location.error, "Location not found.")}</AlertDescription>
      </Alert>
    );
  }
  const loc = location.data.data;
  const b = billTo.data?.data;
  const removed = loc.removed_at !== null;
  const street = [loc.address, loc.address2].filter(Boolean).join(", ");
  const place = [loc.city, [loc.state, loc.zip].filter(Boolean).join(" ")]
    .filter(Boolean)
    .join(", ");

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Breadcrumbs trail={loc.trail} />
        <h1 className="mt-2 flex flex-wrap items-center gap-3 text-3xl">
          {loc.pestpac_company ?? "Unnamed location"}
          {removed && <Badge variant="outline">No longer under this bill-to</Badge>}
          {!removed && !loc.pestpac_active && <Badge variant="warning">Inactive in PestPac</Badge>}
        </h1>
        <p className="text-muted-foreground">
          LocationID {loc.pestpac_location_id}
          {loc.pestpac_location_code && ` · code ${loc.pestpac_location_code}`}
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Location</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
            <span>
              {street}
              {street && place && <br />}
              {place}
            </span>
            <span>
              {loc.phone}
              {loc.phone && loc.email && <br />}
              {loc.email && (
                <a href={`mailto:${loc.email}`} className="text-primary hover:underline">
                  {loc.email}
                </a>
              )}
            </span>
            <span className="text-muted-foreground">
              {[loc.account_type, loc.pestpac_type].filter(Boolean).join(" · ")}
            </span>
          </div>
          {/* Removed locations can't be synced (the API answers 409). */}
          {!removed && (
            <>
              <SyncJobPanel
                billToId={loc.bill_to_id}
                locationId={loc.id}
                canSync={b !== undefined && can("bill_tos:write", b.operator_id)}
                onFinished={onSynced}
              />
              {/* Documents and conditions: on request, not with orders. */}
              <SyncJobPanel
                billToId={loc.bill_to_id}
                locationId={loc.id}
                kind="location"
                canSync={b !== undefined && can("bill_tos:write", b.operator_id)}
                onFinished={onLocationSynced}
              />
            </>
          )}
        </CardContent>
      </Card>

      {b && can("reports:read", b.operator_id) && (
        <Card>
          <CardHeader>
            <CardTitle>Reports</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-6">
            <LocationServiceReports
              companyId={b.company_id}
              locationId={loc.id}
              canWrite={can("reports:write", b.operator_id)}
            />
            <LocationReports
              companyId={b.company_id}
              locationId={loc.id}
              pestpacLocationId={loc.pestpac_location_id}
            />
          </CardContent>
        </Card>
      )}

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-xl">Service orders</h2>
          <OrderStatusSelect value={status} onChange={setStatus} />
        </div>
        <ServiceOrderList query={orders} status={status} showLocation={false} />
      </section>

      {b && can("billing:read", b.operator_id) && <LocationInvoices locationId={loc.id} />}

      <LocationConditions locationId={loc.id} />

      <LocationDocuments locationId={loc.id} />

      <section className="flex flex-col gap-3">
        <h2 className="text-xl">Notes{notes.data && ` (${notes.data.data.length})`}</h2>
        {notes.isPending && <p className="text-muted-foreground">Loading…</p>}
        {notes.isError && (
          <Alert variant="destructive">
            <AlertDescription>
              {errorMessage(notes.error, "Could not load notes.")}
            </AlertDescription>
          </Alert>
        )}
        {notes.data && (
          <div className="border border-border bg-card">
            <NoteList
              notes={notes.data.data}
              empty="No notes from PestPac yet. They're collected when service orders sync."
            />
          </div>
        )}
      </section>
    </div>
  );
}
