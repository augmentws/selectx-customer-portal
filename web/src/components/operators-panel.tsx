"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/api/errors";
import {
  getOperatorsListOperatorsQueryKey,
  useOperatorsCreateOperator,
  useOperatorsListOperators,
} from "@/lib/api/generated/operators/operators";
import { Can, usePermissions } from "@/lib/permissions";

const schema = z.object({
  name: z.string().trim().min(1, "Name is required").max(200),
  slug: z
    .string()
    .trim()
    .regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/, "Lowercase letters, numbers, and single hyphens"),
  pestpac_tenant_id: z.string().trim().min(1, "PestPac tenant ID is required").max(64),
});
type FormValues = z.infer<typeof schema>;

function CreateOperatorForm() {
  const queryClient = useQueryClient();
  const create = useOperatorsCreateOperator({
    mutation: {
      onSuccess: () =>
        queryClient.invalidateQueries({ queryKey: getOperatorsListOperatorsQueryKey() }),
    },
  });
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  const onSubmit = async (data: FormValues) => {
    await create.mutateAsync({ data });
    reset();
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Add operator</CardTitle>
      </CardHeader>
      <CardContent>
        <form
          onSubmit={handleSubmit(onSubmit)}
          className="grid gap-4 sm:grid-cols-[1fr_1fr_1fr_auto] sm:items-end"
          noValidate
        >
          <div className="flex flex-col gap-2">
            <Label htmlFor="op-name">Name</Label>
            <Input id="op-name" {...register("name")} />
            {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="op-slug">Slug</Label>
            <Input id="op-slug" placeholder="long-island" {...register("slug")} />
            {errors.slug && <p className="text-sm text-destructive">{errors.slug.message}</p>}
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="op-pestpac">PestPac tenant ID</Label>
            <Input id="op-pestpac" placeholder="115060" {...register("pestpac_tenant_id")} />
            {errors.pestpac_tenant_id && (
              <p className="text-sm text-destructive">{errors.pestpac_tenant_id.message}</p>
            )}
          </div>
          <Button type="submit" disabled={create.isPending}>
            Add
          </Button>
        </form>
        {create.isError && (
          <Alert variant="destructive" className="mt-4">
            <AlertDescription>{errorMessage(create.error)}</AlertDescription>
          </Alert>
        )}
      </CardContent>
    </Card>
  );
}

export function OperatorsPanel() {
  const { platformTenantId } = usePermissions();
  const operators = useOperatorsListOperators();

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Operators</h1>
        <p className="text-muted-foreground">Operating entities, each linked to a PestPac tenant.</p>
      </div>

      {platformTenantId && (
        <Can perm="operators:write" tenantId={platformTenantId}>
          <CreateOperatorForm />
        </Can>
      )}

      {operators.isPending && <p className="text-muted-foreground">Loading…</p>}
      {operators.isError && (
        <Alert variant="destructive">
          <AlertDescription>{errorMessage(operators.error, "Could not load operators.")}</AlertDescription>
        </Alert>
      )}
      {operators.data && (
        <ul className="divide-y divide-border rounded-lg border border-border bg-card">
          {operators.data.data.length === 0 && (
            <li className="p-4 text-muted-foreground">No operators yet.</li>
          )}
          {operators.data.data.map((op) => (
            <li key={op.id}>
              <Link
                href={`/operators/${op.id}`}
                className="flex items-center justify-between gap-4 p-4 hover:bg-muted"
              >
                <span className="font-medium">{op.name}</span>
                <span className="flex items-center gap-2 text-sm text-muted-foreground">
                  <span>PestPac {op.pestpac_tenant_id}</span>
                  {!op.is_active && <Badge variant="secondary">Inactive</Badge>}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
