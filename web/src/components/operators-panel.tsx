"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { AddDialog } from "@/components/add-dialog";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/api/errors";
import {
  getOperatorsListOperatorsQueryKey,
  useOperatorsCreateOperator,
  useOperatorsListOperators,
} from "@/lib/api/generated/operators/operators";
import { Can, usePermissions } from "@/lib/permissions";
import { OPERATORS_HREF, useHomeHref } from "@/lib/use-home";

const schema = z.object({
  name: z.string().trim().min(1, "Name is required").max(200),
  slug: z
    .string()
    .trim()
    .regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/, "Lowercase letters, numbers, and single hyphens"),
  pestpac_tenant_id: z.string().trim().min(1, "PestPac tenant ID is required").max(64),
});
type FormValues = z.infer<typeof schema>;

function CreateOperatorForm({ onDone }: { onDone: () => void }) {
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
    onDone();
  };

  return (
    <div>
      <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4" noValidate>
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
        <div>
          <Button type="submit" disabled={create.isPending}>
            Add operator
          </Button>
        </div>
      </form>
      {create.isError && (
        <Alert variant="destructive" className="mt-4">
          <AlertDescription>{errorMessage(create.error)}</AlertDescription>
        </Alert>
      )}
    </div>
  );
}

export function OperatorsPanel() {
  const { platformTenantId } = usePermissions();
  const operators = useOperatorsListOperators();
  const router = useRouter();
  const home = useHomeHref();
  useEffect(() => {
    if (home !== OPERATORS_HREF) router.replace(home);
  }, [home, router]);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-3xl">Operators</h1>
          <p className="text-muted-foreground">
            Operating entities, each linked to a PestPac tenant.
          </p>
        </div>
        {platformTenantId && (
          <Can perm="operators:write" tenantId={platformTenantId}>
            <AddDialog label="Add operator" title="Add operator">
              {(close) => <CreateOperatorForm onDone={close} />}
            </AddDialog>
          </Can>
        )}
      </div>

      {operators.isPending && <p className="text-muted-foreground">Loading…</p>}
      {operators.isError && (
        <Alert variant="destructive">
          <AlertDescription>
            {errorMessage(operators.error, "Could not load operators.")}
          </AlertDescription>
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
                  {!op.is_active && <Badge variant="outline">Inactive</Badge>}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
