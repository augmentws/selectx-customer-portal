"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/api/errors";
import { useBillTosUpdateBillTo } from "@/lib/api/generated/bill-tos/bill-tos";
import { usePestpacGetConnection } from "@/lib/api/generated/pestpac/pestpac";
import {
  getCompaniesListBillTosQueryKey,
  useCompaniesGetCompany,
  useCompaniesListBillTos,
  useCompaniesOnboardBillTo,
} from "@/lib/api/generated/companies/companies";
import { Can, usePermissions } from "@/lib/permissions";

const schema = z.object({
  pestpac_bill_to_id: z.coerce
    .number<string>()
    .int("Whole number")
    .positive("Enter the PestPac BillToID"),
  name: z.string().trim().min(1, "Name is required").max(200),
  description: z.string().trim().max(1000),
});
type FormInput = z.input<typeof schema>;
type FormOutput = z.output<typeof schema>;

function OnboardBillToForm({ companyId, operatorId }: { companyId: string; operatorId: string }) {
  const queryClient = useQueryClient();
  const connection = usePestpacGetConnection(operatorId);
  const ready = connection.data?.data.status === "verified";
  const onboard = useCompaniesOnboardBillTo({
    mutation: {
      onSuccess: () =>
        queryClient.invalidateQueries({ queryKey: getCompaniesListBillTosQueryKey(companyId) }),
    },
  });
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormInput, unknown, FormOutput>({
    resolver: zodResolver(schema),
    defaultValues: { pestpac_bill_to_id: "", name: "", description: "" },
  });

  const onSubmit = async ({ description, ...rest }: FormOutput) => {
    await onboard.mutateAsync({ companyId, data: { ...rest, description: description || null } });
    reset();
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Onboard bill-to</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {connection.data && !ready && (
          <Alert>
            <AlertDescription>
              Set up and verify this operator&apos;s{" "}
              <Link href={`/operators/${operatorId}?tab=pestpac`} className="underline">
                PestPac API access
              </Link>{" "}
              before onboarding bill-tos. Each BillToID is checked against PestPac.
            </AlertDescription>
          </Alert>
        )}
        <fieldset disabled={!ready} className="contents">
          <form onSubmit={handleSubmit(onSubmit)} className="grid gap-4 sm:grid-cols-2" noValidate>
            <div className="flex flex-col gap-2">
              <Label htmlFor="billto-id">PestPac BillToID</Label>
              <Input id="billto-id" inputMode="numeric" {...register("pestpac_bill_to_id")} />
              {errors.pestpac_bill_to_id && (
                <p className="text-sm text-destructive">{errors.pestpac_bill_to_id.message}</p>
              )}
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="billto-name">Name</Label>
              <Input id="billto-name" {...register("name")} />
              {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
            </div>
            <div className="flex flex-col gap-2 sm:col-span-2">
              <Label htmlFor="billto-description">Description</Label>
              <Input
                id="billto-description"
                placeholder="e.g. Northeast region, covers 14 locations"
                {...register("description")}
              />
              {errors.description && (
                <p className="text-sm text-destructive">{errors.description.message}</p>
              )}
            </div>
            <div className="sm:col-span-2">
              <Button type="submit" disabled={onboard.isPending}>
                Onboard
              </Button>
            </div>
          </form>
        </fieldset>
        {onboard.isError && (
          <Alert variant="destructive">
            <AlertDescription>{errorMessage(onboard.error)}</AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  );
}

export function CompanyDetail() {
  const { companyId } = useParams<{ companyId: string }>();
  const queryClient = useQueryClient();
  const { can } = usePermissions();
  const company = useCompaniesGetCompany(companyId);
  const billTos = useCompaniesListBillTos(companyId);
  const update = useBillTosUpdateBillTo({
    mutation: {
      onSuccess: () =>
        queryClient.invalidateQueries({ queryKey: getCompaniesListBillTosQueryKey(companyId) }),
    },
  });

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
        <h1 className="mt-2 flex items-center gap-3 text-2xl font-semibold tracking-tight">
          {c.name}
          {!c.is_active && <Badge variant="secondary">Inactive</Badge>}
        </h1>
        <p className="text-muted-foreground">
          Bill-tos onboarded to the portal. Service orders are captured only for these.
        </p>
      </div>

      <Can perm="bill_tos:write" tenantId={c.operator_id}>
        <OnboardBillToForm companyId={companyId} operatorId={c.operator_id} />
      </Can>

      {update.isError && (
        <Alert variant="destructive">
          <AlertDescription>{errorMessage(update.error)}</AlertDescription>
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
              <div className="flex flex-col gap-1">
                <span className="flex items-center gap-2 font-medium">
                  {b.name}
                  <span className="text-sm font-normal text-muted-foreground">
                    BillToID {b.pestpac_bill_to_id}
                  </span>
                  {!b.is_active && <Badge variant="secondary">Inactive</Badge>}
                </span>
                {b.description && (
                  <span className="text-sm text-muted-foreground">{b.description}</span>
                )}
              </div>
              {canWrite && (
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
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
