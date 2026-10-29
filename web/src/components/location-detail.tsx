"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useCallback } from "react";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { LocationConditions } from "@/components/location-conditions";
import { LocationDocuments } from "@/components/location-documents";
import { LocationInvoices } from "@/components/location-invoices";
import { LocationServiceReports } from "@/components/location-service-reports";
import { NoteList } from "@/components/note-list";
import { PostedServiceOrders } from "@/components/posted-service-orders";
import { useServiceReportTemplates } from "@/components/report-action";
import { LocationReports } from "@/components/report-templates";
import { formatPestPacDate } from "@/components/service-order-list";
import { PestPacSync } from "@/components/sync-job-panel";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/page-tabs";
import { useDocumentTitle } from "@/lib/use-document-title";
import { errorMessage } from "@/lib/api/errors";
import { useBillTosGetBillTo } from "@/lib/api/generated/bill-tos/bill-tos";
import {
  getLocationsGetLocationQueryKey,
  getLocationsListConditionsQueryKey,
  getLocationsListDocumentsQueryKey,
  getLocationsListNotesQueryKey,
  getLocationsListInvoicedServiceOrdersQueryKey,
  getLocationsListOpenServiceOrdersQueryKey,
  getLocationsListPostedServiceOrdersQueryKey,
  useLocationsGetLocation,
  useLocationsListNotes,
} from "@/lib/api/generated/locations/locations";
import { usePermissions } from "@/lib/permissions";
import { useUrlTab } from "@/lib/use-url-tab";
import { LocationRiskInspections } from "@/components/risk-inspections-list";

const TABS = [
  "overview",
  "orders",
  "conditions",
  "risk",
  "documents",
  "invoices",
  "notes",
] as const;
const ORDER_TABS = ["posted", "invoiced", "open"] as const;

export function LocationDetail() {
  const { locationId } = useParams<{ locationId: string }>();
  const queryClient = useQueryClient();
  const { can } = usePermissions();
  const [tab, setTab] = useUrlTab(TABS, "overview");
  const [ordersTab, setOrdersTab] = useUrlTab(ORDER_TABS, "posted", "orders");
  const location = useLocationsGetLocation(locationId);
  const billToId = location.data?.data.bill_to_id ?? "";
  const billTo = useBillTosGetBillTo(billToId, { query: { enabled: billToId !== "" } });
  const notes = useLocationsListNotes(locationId);
  const templates = useServiceReportTemplates(
    billTo.data?.data.company_id,
    billTo.data?.data.operator_id,
  );
  const l = location.data?.data;
  useDocumentTitle(
    l && (l.pestpac_company ?? `LocationID ${l.pestpac_location_id}`),
    l?.trail.find((c) => c.kind === "company")?.name,
  );

  const onSynced = useCallback(() => {
    for (const queryKey of [
      getLocationsGetLocationQueryKey(locationId),
      getLocationsListPostedServiceOrdersQueryKey(locationId),
      getLocationsListInvoicedServiceOrdersQueryKey(locationId),
      getLocationsListOpenServiceOrdersQueryKey(locationId),
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
  const canBilling = b !== undefined && can("billing:read", b.operator_id);
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

      {/* Invoices need billing:read; a URL naming it falls back to the overview for others. */}
      <Tabs value={tab === "invoices" && !canBilling ? "overview" : tab} onValueChange={setTab}>
        <TabsList className="flex-wrap">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="orders">
            Service orders{(loc.open_order_count ?? 0) > 0 && ` (${loc.open_order_count} open)`}
          </TabsTrigger>
          <TabsTrigger value="conditions">Conditions</TabsTrigger>
          <TabsTrigger value="risk">Risk inspections</TabsTrigger>
          <TabsTrigger value="documents">Documents</TabsTrigger>
          {canBilling && <TabsTrigger value="invoices">Invoices</TabsTrigger>}
          <TabsTrigger value="notes">
            Notes{notes.data && ` (${notes.data.data.length})`}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="flex flex-col gap-6 pt-4">
          <Card>
            <CardHeader>
              <CardTitle>Location</CardTitle>
            </CardHeader>
            <CardContent>
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
                  <br />
                  {(loc.worked_order_count ?? 0) > 0 &&
                    `${loc.worked_order_count} worked, awaiting billing · `}
                  {loc.last_service_at
                    ? `Last serviced ${formatPestPacDate(loc.last_service_at)}`
                    : "No service recorded"}
                </span>
              </div>
            </CardContent>
          </Card>

          {/* Removed locations can't be synced (the API answers 409). */}
          {!removed && (
            <PestPacSync
              billToId={loc.bill_to_id}
              locationId={loc.id}
              pestpacLocationId={loc.pestpac_location_id}
              canSync={b !== undefined && can("bill_tos:write", b.operator_id)}
              onOrdersSynced={onSynced}
              onLocationSynced={onLocationSynced}
            />
          )}

          {b && can("reports:read", b.operator_id) && (
            <Card>
              <CardHeader>
                <CardTitle>Reports</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-6">
                <LocationServiceReports locationId={loc.id} canStart={templates.length > 0} />
                <LocationReports
                  companyId={b.company_id}
                  locationId={loc.id}
                  pestpacLocationId={loc.pestpac_location_id}
                />
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="orders" className="pt-4">
          {/* As on the customer page; invoiced orders need billing:read. */}
          <Tabs
            value={ordersTab === "invoiced" && !canBilling ? "posted" : ordersTab}
            onValueChange={setOrdersTab}
          >
            <TabsList>
              <TabsTrigger value="posted">Posted</TabsTrigger>
              {canBilling && <TabsTrigger value="invoiced">Invoiced</TabsTrigger>}
              <TabsTrigger value="open">Open</TabsTrigger>
            </TabsList>
            {ORDER_TABS.map((kind) => (
              <TabsContent key={kind} value={kind} className="pt-4">
                {b && (
                  <PostedServiceOrders
                    kind={kind}
                    locationId={loc.id}
                    companyId={b.company_id}
                    operatorId={b.operator_id}
                  />
                )}
              </TabsContent>
            ))}
          </Tabs>
        </TabsContent>

        <TabsContent value="conditions" className="pt-4">
          <LocationConditions locationId={loc.id} />
        </TabsContent>

        <TabsContent value="risk" className="pt-4">
          <LocationRiskInspections
            locationId={locationId}

            locationName={loc.pestpac_company ?? `LocationID ${loc.pestpac_location_id}`}
          />
        </TabsContent>

        <TabsContent value="documents" className="pt-4">
          <LocationDocuments locationId={loc.id} />
        </TabsContent>

        {canBilling && (
          <TabsContent value="invoices" className="pt-4">
            <LocationInvoices locationId={loc.id} />
          </TabsContent>
        )}

        <TabsContent value="notes" className="flex flex-col gap-3 pt-4">
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
                empty="No notes from PestPac yet. They're collected when orders and notes sync."
              />
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
