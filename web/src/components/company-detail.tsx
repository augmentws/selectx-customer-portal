"use client";

import { useQueryClient } from "@tanstack/react-query";
import { LayoutDashboard } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect } from "react";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { AddDialog } from "@/components/add-dialog";
import { BillToDetailLines, OnboardBillTo } from "@/components/bill-to-onboarding";
import { LocationSyncResult } from "@/components/location-sync-result";
import { InvoicedOrders } from "@/components/invoiced-orders";
import { LocationsTable } from "@/components/locations-table";
import { CompanyRiskInspections } from "@/components/risk-inspections-list";
import { MembersPanel } from "@/components/members-panel";
import { PostedServiceOrders } from "@/components/posted-service-orders";
import { ReportTemplatesSection } from "@/components/report-templates";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/page-tabs";
import { useDocumentTitle } from "@/lib/use-document-title";
import { errorMessage } from "@/lib/api/errors";
import {
  useBillTosRefreshBillTo,
  useBillTosUpdateBillTo,
} from "@/lib/api/generated/bill-tos/bill-tos";
import {
  getCompaniesListBillTosQueryKey,
  useCompaniesGetCompany,
  useCompaniesListBillTos,
  useCompaniesListLocations,
} from "@/lib/api/generated/companies/companies";
import { Can, usePermissions } from "@/lib/permissions";
import { useUrlTab } from "@/lib/use-url-tab";

export function CompanyDetail() {
  const { companyId } = useParams<{ companyId: string }>();
  const [tab, setTab] = useUrlTab(
    ["bill-tos", "locations", "posted", "invoiced", "open", "risk", "templates", "members"],
    "bill-tos",
  );
  const queryClient = useQueryClient();
  const router = useRouter();
  const { can, me } = usePermissions();
  // A customer's user can open only the company's dashboard, so this page sends them there.
  const grant = me?.company_memberships.find((g) => g.company_id === companyId);
  const companyUser = grant !== undefined && !can("companies:read", grant.operator_id);
  useEffect(() => {
    if (companyUser) router.replace(`/companies/${companyId}/dashboard`);
  }, [companyUser, companyId, router]);
  const company = useCompaniesGetCompany(companyId, { query: { enabled: !companyUser } });
  const billTos = useCompaniesListBillTos(companyId, { query: { enabled: !companyUser } });
  // Every store across the bill-tos: fetched only once the tab is opened.
  const locations = useCompaniesListLocations(companyId, {
    query: { enabled: tab === "locations" && !companyUser },
  });
  useDocumentTitle(company.data?.data.name);
  const invalidateList = () =>
    queryClient.invalidateQueries({ queryKey: getCompaniesListBillTosQueryKey(companyId) });
  const update = useBillTosUpdateBillTo({ mutation: { onSuccess: invalidateList } });
  const refresh = useBillTosRefreshBillTo({ mutation: { onSuccess: invalidateList } });
  const mutationError = update.error ?? refresh.error;

  if (companyUser || company.isPending) return <p className="text-muted-foreground">Loading…</p>;
  if (company.isError) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{errorMessage(company.error, "Company not found.")}</AlertDescription>
      </Alert>
    );
  }
  const c = company.data.data;
  const canWrite = can("bill_tos:write", c.operator_id);

  // Tabs the caller can't see fall back to Bill-tos.
  const shownTab =
    (tab === "invoiced" && !can("billing:read", c.operator_id)) ||
    (tab === "templates" && !can("reports:read", c.operator_id)) ||
    (tab === "members" && !can("members:read", c.operator_id))
      ? "bill-tos"
      : tab;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Breadcrumbs trail={c.trail} />
        <h1 className="mt-2 flex items-center gap-3 text-3xl">
          {c.name}
          {!c.is_active && <Badge variant="outline">Inactive</Badge>}
        </h1>
        {billTos.data && (
          <p className="text-muted-foreground">
            {billTos.data.data.length === 1 ? "1 bill-to" : `${billTos.data.data.length} bill-tos`}{" "}
            onboarded from PestPac
          </p>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <Can perm="dashboards:read" tenantId={c.operator_id}>
            <Link
              href={`/companies/${companyId}/dashboard`}
              className={buttonVariants({ variant: "outline", size: "sm" })}
            >
              <LayoutDashboard aria-hidden />
              Dashboard
            </Link>
          </Can>
          {/* Onboarding adds to the Bill-tos list, so it's offered only there. */}
          {shownTab === "bill-tos" && (
            <Can perm="bill_tos:write" tenantId={c.operator_id}>
              <AddDialog
                label="Onboard bill-to"
                title="Onboard bill-to"
                description="Look up a BillToID in PestPac, check its details, then onboard it."
              >
                {() => <OnboardBillTo companyId={companyId} operatorId={c.operator_id} />}
              </AddDialog>
            </Can>
          )}
        </div>
      </div>

      {/* Tabs the user can't see (by permission) fall back to Bill-tos when named in a URL. */}
      <Tabs value={shownTab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="bill-tos">Bill-tos</TabsTrigger>
          <TabsTrigger value="locations">Locations</TabsTrigger>
          <TabsTrigger value="posted">Posted service orders</TabsTrigger>
          {can("billing:read", c.operator_id) && (
            <TabsTrigger value="invoiced">Invoiced orders</TabsTrigger>
          )}
          <TabsTrigger value="open">Open orders</TabsTrigger>
          <TabsTrigger value="risk">Risk inspections</TabsTrigger>
          {can("reports:read", c.operator_id) && (
            <TabsTrigger value="templates">Report templates</TabsTrigger>
          )}
          {can("members:read", c.operator_id) && <TabsTrigger value="members">Members</TabsTrigger>}
        </TabsList>
        <TabsContent value="bill-tos" className="flex flex-col gap-3 pt-4">
          {refresh.isSuccess && (
            <LocationSyncResult
              summary={refresh.data.data.locations_sync}
              label={`Refreshed ${refresh.data.data.name}`}
            />
          )}
          {mutationError && (
            <Alert variant="destructive">
              <AlertDescription>{errorMessage(mutationError)}</AlertDescription>
            </Alert>
          )}
          {billTos.isPending && <p className="text-muted-foreground">Loading…</p>}
          {billTos.isError && (
            <Alert variant="destructive">
              <AlertDescription>
                {errorMessage(billTos.error, "Could not load bill-tos.")}
              </AlertDescription>
            </Alert>
          )}
          {billTos.data && (
            <ul className="divide-y divide-border rounded-lg border border-border bg-card">
              {billTos.data.data.length === 0 && (
                <li className="p-4 text-muted-foreground">No bill-tos onboarded yet.</li>
              )}
              {billTos.data.data.map((b) => (
                <li key={b.id} className="flex flex-wrap items-start justify-between gap-3 p-4">
                  <div className="flex flex-col gap-2">
                    <span className="flex flex-wrap items-center gap-2 font-medium">
                      <Link href={`/bill-tos/${b.id}`} className="text-primary hover:underline">
                        {b.name}
                      </Link>
                      <span className="text-sm font-normal text-muted-foreground">
                        BillToID {b.pestpac_bill_to_id}
                      </span>
                      {!b.is_active && <Badge variant="outline">Inactive</Badge>}
                    </span>
                    {b.description && (
                      <span className="text-sm text-muted-foreground">{b.description}</span>
                    )}
                    {b.pestpac_fetched_at ? (
                      <>
                        <BillToDetailLines details={b} />
                        <span className="text-xs text-muted-foreground">
                          From PestPac {new Date(b.pestpac_fetched_at).toLocaleString()}
                        </span>
                      </>
                    ) : (
                      <span className="text-sm text-muted-foreground">
                        PestPac details not fetched yet.
                      </span>
                    )}
                  </div>
                  {/* Open the bill-to top right; occasional admin actions bottom right. */}
                  <div className="flex flex-col items-end justify-between gap-3 self-stretch">
                    <Link href={`/bill-tos/${b.id}`} className={buttonVariants({ size: "sm" })}>
                      Locations ({b.location_count})
                    </Link>
                    {canWrite && (
                      <div className="flex gap-2">
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={refresh.isPending}
                          onClick={() => refresh.mutate({ billToId: b.id })}
                        >
                          Refresh from PestPac
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          disabled={update.isPending}
                          onClick={() =>
                            update.mutate({ billToId: b.id, data: { is_active: !b.is_active } })
                          }
                        >
                          {b.is_active ? "Deactivate" : "Reactivate"}
                        </Button>
                      </div>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </TabsContent>
        <TabsContent value="locations" className="pt-4">
          <LocationsTable
            locations={locations}
            // With several bill-tos, each row says which one the store is under.
            billTos={
              (billTos.data?.data.length ?? 0) > 1
                ? new Map(billTos.data?.data.map((b) => [b.id, b.name]))
                : undefined
            }
            emptyText="PestPac lists no locations under this company's bill-tos."
            exportName={`${c.name} locations`}
          />
        </TabsContent>
        <TabsContent value="posted" className="pt-4">
          <PostedServiceOrders companyId={companyId} operatorId={c.operator_id} />
        </TabsContent>
        {can("billing:read", c.operator_id) && (
          <TabsContent value="invoiced" className="pt-4">
            <InvoicedOrders companyId={companyId} />
          </TabsContent>
        )}
        <TabsContent value="open" className="pt-4">
          <PostedServiceOrders kind="open" companyId={companyId} operatorId={c.operator_id} />
        </TabsContent>
        <TabsContent value="risk" className="pt-4">
          <CompanyRiskInspections companyId={companyId} companyName={c.name} />
        </TabsContent>
        {can("reports:read", c.operator_id) && (
          <TabsContent value="templates" className="pt-4">
            <ReportTemplatesSection companyId={companyId} operatorId={c.operator_id} />
          </TabsContent>
        )}
        {can("members:read", c.operator_id) && (
          <TabsContent value="members" className="flex flex-col gap-3 pt-4">
            <p className="text-sm text-muted-foreground">
              The company&apos;s own users. They see only this company&apos;s dashboard.
            </p>
            <MembersPanel target={{ kind: "company", companyId, operatorId: c.operator_id }} />
          </TabsContent>
        )}
      </Tabs>
    </div>
  );
}
