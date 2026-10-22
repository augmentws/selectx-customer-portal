"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";

import { BillToDetailLines, OnboardBillToCard } from "@/components/bill-to-onboarding";
import { LocationSyncResult } from "@/components/location-sync-result";
import { ReportTemplatesSection } from "@/components/report-templates";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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

export function CompanyDetail() {
  const { companyId } = useParams<{ companyId: string }>();
  const queryClient = useQueryClient();
  const { can } = usePermissions();
  const company = useCompaniesGetCompany(companyId);
  const billTos = useCompaniesListBillTos(companyId);
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
        <Link
          href={`/operators/${c.operator_id}`}
          className="text-sm text-muted-foreground hover:text-foreground"
        >
          ← Operator
        </Link>
        <h1 className="mt-2 flex items-center gap-3 text-3xl">
          {c.name}
          {!c.is_active && <Badge variant="outline">Inactive</Badge>}
        </h1>
        <p className="text-muted-foreground">
          Bill-tos onboarded to the portal. Service orders are captured only for these.
        </p>
      </div>

      <Can perm="bill_tos:write" tenantId={c.operator_id}>
        <OnboardBillToCard companyId={companyId} operatorId={c.operator_id} />
      </Can>

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
                  <Link
                    href={`/bill-tos/${b.id}`}
                    className="text-sm font-normal text-primary hover:underline"
                  >
                    {b.location_count} {b.location_count === 1 ? "location" : "locations"} →
                  </Link>
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
            </li>
          ))}
        </ul>
      )}

      <Can perm="reports:read" tenantId={c.operator_id}>
        <ReportTemplatesSection companyId={companyId} operatorId={c.operator_id} />
      </Can>
    </div>
  );
}
