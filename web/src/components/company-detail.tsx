"use client";

import { useQueryClient } from "@tanstack/react-query";
import { LayoutDashboard } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { BillToDetailLines, OnboardBillToCard } from "@/components/bill-to-onboarding";
import { LocationSyncResult } from "@/components/location-sync-result";
import { InvoicedOrders } from "@/components/invoiced-orders";
import { PostedServiceOrders } from "@/components/posted-service-orders";
import { ReportTemplatesSection } from "@/components/report-templates";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
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
} from "@/lib/api/generated/companies/companies";
import { Can, usePermissions } from "@/lib/permissions";
import { cn } from "@/lib/utils";
import { useUrlTab } from "@/lib/use-url-tab";

export function CompanyDetail() {
  const { companyId } = useParams<{ companyId: string }>();
  const [tab, setTab] = useUrlTab(["bill-tos", "posted", "invoiced"], "bill-tos");
  const queryClient = useQueryClient();
  const { can } = usePermissions();
  const company = useCompaniesGetCompany(companyId);
  const billTos = useCompaniesListBillTos(companyId);
  useDocumentTitle(company.data?.data.name);
  const invalidateList = () =>
    queryClient.invalidateQueries({ queryKey: getCompaniesListBillTosQueryKey(companyId) });
  const update = useBillTosUpdateBillTo({ mutation: { onSuccess: invalidateList } });
  const refresh = useBillTosRefreshBillTo({ mutation: { onSuccess: invalidateList } });
  const mutationError = update.error ?? refresh.error;

  if (company.isPending) return <p className="text-muted-foreground">Loading…</p>;
  if (company.isError) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{errorMessage(company.error, "Company not found.")}</AlertDescription>
      </Alert>
    );
  }
  const c = company.data.data;
  const canWrite = can("bill_tos:write", c.operator_id);

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
        <Can perm="dashboards:read" tenantId={c.operator_id}>
          <Link
            href={`/companies/${companyId}/dashboard`}
            className={cn(buttonVariants({ variant: "outline", size: "sm" }), "mt-3")}
          >
            <LayoutDashboard aria-hidden />
            Dashboard
          </Link>
        </Can>
      </div>

      <Can perm="bill_tos:write" tenantId={c.operator_id}>
        <OnboardBillToCard companyId={companyId} operatorId={c.operator_id} />
      </Can>

      {/* Invoiced orders need billing:read; a URL naming it falls back for others. */}
      <Tabs
        value={tab === "invoiced" && !can("billing:read", c.operator_id) ? "bill-tos" : tab}
        onValueChange={setTab}
      >
        <TabsList>
          <TabsTrigger value="bill-tos">Bill-tos</TabsTrigger>
          <TabsTrigger value="posted">Posted service orders</TabsTrigger>
          {can("billing:read", c.operator_id) && (
            <TabsTrigger value="invoiced">Invoiced orders</TabsTrigger>
          )}
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
                      {b.name}
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
        <TabsContent value="posted" className="pt-4">
          <PostedServiceOrders companyId={companyId} operatorId={c.operator_id} />
        </TabsContent>
        {can("billing:read", c.operator_id) && (
          <TabsContent value="invoiced" className="pt-4">
            <InvoicedOrders companyId={companyId} />
          </TabsContent>
        )}
      </Tabs>

      <Can perm="reports:read" tenantId={c.operator_id}>
        <ReportTemplatesSection companyId={companyId} operatorId={c.operator_id} />
      </Can>
    </div>
  );
}
