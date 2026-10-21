"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { LocationSyncResult } from "@/components/location-sync-result";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/api/errors";
import {
  getCompaniesListBillTosQueryKey,
  useCompaniesLookupBillTo,
  useCompaniesOnboardBillTo,
} from "@/lib/api/generated/companies/companies";
import type { BillToLookup, BillToSynced, PestPacBillToDetails } from "@/lib/api/generated/model";
import { usePestpacGetConnection } from "@/lib/api/generated/pestpac/pestpac";

/** PestPac's identifying details for a bill-to: code, company, address, phone, type. */
export function BillToDetailLines({
  details,
}: {
  details: Pick<
    PestPacBillToDetails,
    | "pestpac_bill_to_code"
    | "pestpac_company"
    | "address"
    | "address2"
    | "city"
    | "state"
    | "zip"
    | "phone"
    | "pestpac_type"
  >;
}) {
  const street = [details.address, details.address2].filter(Boolean).join(", ");
  const place = [details.city, [details.state, details.zip].filter(Boolean).join(" ")]
    .filter(Boolean)
    .join(", ");
  return (
    <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
      {details.pestpac_company && (
        <>
          <dt className="text-muted-foreground">Company</dt>
          <dd>{details.pestpac_company}</dd>
        </>
      )}
      {details.pestpac_bill_to_code && (
        <>
          <dt className="text-muted-foreground">Bill-to code</dt>
          <dd>{details.pestpac_bill_to_code}</dd>
        </>
      )}
      {(street || place) && (
        <>
          <dt className="text-muted-foreground">Address</dt>
          <dd>
            {street}
            {street && place && <br />}
            {place}
          </dd>
        </>
      )}
      {details.phone && (
        <>
          <dt className="text-muted-foreground">Phone</dt>
          <dd>{details.phone}</dd>
        </>
      )}
      {details.pestpac_type && (
        <>
          <dt className="text-muted-foreground">Type</dt>
          <dd>{details.pestpac_type}</dd>
        </>
      )}
    </dl>
  );
}

const lookupSchema = z.object({
  pestpac_bill_to_id: z.coerce
    .number<string>()
    .int("Whole number")
    .positive("Enter the PestPac BillToID"),
});

const confirmSchema = z.object({
  name: z.string().trim().min(1, "Name is required").max(200),
  description: z.string().trim().max(1000),
});
type ConfirmValues = z.infer<typeof confirmSchema>;

function ConfirmOnboarding({
  companyId,
  lookup,
  onDone,
}: {
  companyId: string;
  lookup: BillToLookup;
  onDone: (onboarded?: BillToSynced) => void;
}) {
  const queryClient = useQueryClient();
  const onboard = useCompaniesOnboardBillTo({
    mutation: {
      onSuccess: () =>
        queryClient.invalidateQueries({ queryKey: getCompaniesListBillTosQueryKey(companyId) }),
    },
  });
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ConfirmValues>({
    resolver: zodResolver(confirmSchema),
    defaultValues: { name: lookup.suggested_name, description: "" },
  });

  const onSubmit = async ({ name, description }: ConfirmValues) => {
    const response = await onboard.mutateAsync({
      companyId,
      data: {
        pestpac_bill_to_id: lookup.details.pestpac_bill_to_id,
        name,
        description: description || null,
      },
    });
    onDone(response.data);
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4" noValidate>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-2">
          <Label htmlFor="billto-name">Name in the portal</Label>
          <Input id="billto-name" {...register("name")} />
          {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
        </div>
        <div className="flex flex-col gap-2">
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
      </div>
      <div className="flex gap-3">
        <Button type="submit" disabled={onboard.isPending}>
          {onboard.isPending ? "Onboarding…" : "Onboard"}
        </Button>
        <Button type="button" variant="ghost" onClick={() => onDone()}>
          Cancel
        </Button>
      </div>
      {onboard.isError && (
        <Alert variant="destructive">
          <AlertDescription>{errorMessage(onboard.error)}</AlertDescription>
        </Alert>
      )}
    </form>
  );
}

export function OnboardBillToCard({
  companyId,
  operatorId,
}: {
  companyId: string;
  operatorId: string;
}) {
  const connection = usePestpacGetConnection(operatorId);
  const ready = connection.data?.data.status === "verified";
  const [lookupId, setLookupId] = useState<number | null>(null);
  const lookup = useCompaniesLookupBillTo(
    companyId,
    { pestpac_bill_to_id: lookupId ?? 0 },
    { query: { enabled: lookupId !== null, retry: false, staleTime: 0, gcTime: 0 } },
  );
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<z.input<typeof lookupSchema>, unknown, z.output<typeof lookupSchema>>({
    resolver: zodResolver(lookupSchema),
    defaultValues: { pestpac_bill_to_id: "" },
  });

  const result = lookup.data?.data;
  const onboardedHere = result?.onboarded_company_id === companyId;

  const [lastOnboarded, setLastOnboarded] = useState<BillToSynced | null>(null);

  const done = (onboarded?: BillToSynced) => {
    setLookupId(null);
    setLastOnboarded(onboarded ?? null);
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
              before onboarding bill-tos. Each BillToID is looked up in PestPac.
            </AlertDescription>
          </Alert>
        )}
        {lastOnboarded && (
          <LocationSyncResult
            summary={lastOnboarded.locations_sync}
            label={`Onboarded ${lastOnboarded.name}`}
          />
        )}
        <fieldset disabled={!ready} className="contents">
          <form
            onSubmit={handleSubmit(({ pestpac_bill_to_id }) => {
              setLastOnboarded(null);
              setLookupId(pestpac_bill_to_id);
            })}
            className="flex items-end gap-3"
            noValidate
          >
            <div className="flex flex-col gap-2">
              <Label htmlFor="billto-id">PestPac BillToID</Label>
              <Input
                id="billto-id"
                inputMode="numeric"
                className="w-48"
                {...register("pestpac_bill_to_id")}
              />
            </div>
            <Button type="submit" variant="secondary" disabled={lookup.isFetching}>
              {lookup.isFetching ? "Looking up…" : "Look up"}
            </Button>
          </form>
        </fieldset>
        {errors.pestpac_bill_to_id && (
          <p className="text-sm text-destructive">{errors.pestpac_bill_to_id.message}</p>
        )}

        {lookup.isError && (
          <Alert variant="destructive">
            <AlertDescription>{errorMessage(lookup.error)}</AlertDescription>
          </Alert>
        )}

        {result && !lookup.isFetching && (
          <div className="flex flex-col gap-4 border-t border-border pt-4">
            <div className="flex items-center gap-2">
              <span className="font-heading text-lg font-medium">
                BillToID {result.details.pestpac_bill_to_id}
              </span>
              {result.onboarded_bill_to_id && (
                <Badge variant="warning">
                  {onboardedHere ? "Already onboarded here" : "Onboarded to another company"}
                </Badge>
              )}
            </div>
            <BillToDetailLines details={result.details} />
            {result.onboarded_bill_to_id ? (
              <div>
                <Button type="button" variant="ghost" onClick={() => done()}>
                  Look up another
                </Button>
              </div>
            ) : (
              <ConfirmOnboarding
                key={result.details.pestpac_bill_to_id}
                companyId={companyId}
                lookup={result}
                onDone={done}
              />
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
