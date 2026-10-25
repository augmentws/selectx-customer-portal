"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { AddDialog } from "@/components/add-dialog";
import { Breadcrumbs } from "@/components/breadcrumbs";
import { MembersPanel } from "@/components/members-panel";
import { PestPacConnectionPanel } from "@/components/pestpac-connection-panel";
import { GoCanvasRequestsPanel } from "@/components/gocanvas-requests-panel";
import { WebhookEventsPanel } from "@/components/webhook-events-panel";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useDocumentTitle } from "@/lib/use-document-title";
import { errorMessage } from "@/lib/api/errors";
import {
  getOperatorsListCompaniesQueryKey,
  useOperatorsCreateCompany,
  useOperatorsGetOperator,
  useOperatorsListCompanies,
} from "@/lib/api/generated/operators/operators";
import { Can, usePermissions } from "@/lib/permissions";
import { useUrlTab } from "@/lib/use-url-tab";

const companySchema = z.object({ name: z.string().trim().min(1, "Name is required").max(200) });

function CreateCompanyForm({ operatorId, onDone }: { operatorId: string; onDone: () => void }) {
  const queryClient = useQueryClient();
  const create = useOperatorsCreateCompany({
    mutation: {
      onSuccess: () =>
        queryClient.invalidateQueries({
          queryKey: getOperatorsListCompaniesQueryKey(operatorId),
        }),
    },
  });
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<z.infer<typeof companySchema>>({ resolver: zodResolver(companySchema) });

  return (
    <div>
      <form
        onSubmit={handleSubmit(async (data) => {
          await create.mutateAsync({ operatorId, data });
          reset();
          onDone();
        })}
        className="flex items-end gap-3"
        noValidate
      >
        <div className="flex flex-1 flex-col gap-2">
          <Label htmlFor="company-name">Name</Label>
          <Input id="company-name" {...register("name")} />
          {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
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
    </div>
  );
}

function CompaniesTab({ operatorId }: { operatorId: string }) {
  const companies = useOperatorsListCompanies(operatorId);
  return (
    <div className="flex flex-col gap-6">
      <Can perm="companies:write" tenantId={operatorId}>
        <div className="flex justify-end">
          <AddDialog label="Add company" title="Add company">
            {(close) => <CreateCompanyForm operatorId={operatorId} onDone={close} />}
          </AddDialog>
        </div>
      </Can>
      {companies.isPending && <p className="text-muted-foreground">Loading…</p>}
      {companies.isError && (
        <Alert variant="destructive">
          <AlertDescription>
            {errorMessage(companies.error, "Could not load companies.")}
          </AlertDescription>
        </Alert>
      )}
      {companies.data && (
        <ul className="divide-y divide-border rounded-lg border border-border bg-card">
          {companies.data.data.length === 0 && (
            <li className="p-4 text-muted-foreground">No companies yet.</li>
          )}
          {companies.data.data.map((c) => (
            <li key={c.id}>
              <Link
                href={`/companies/${c.id}`}
                className="flex items-center justify-between p-4 hover:bg-muted"
              >
                <span className="font-medium">{c.name}</span>
                {!c.is_active && <Badge variant="outline">Inactive</Badge>}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function OperatorDetail() {
  const { operatorId } = useParams<{ operatorId: string }>();
  const [tab, setTab] = useUrlTab(
    ["companies", "members", "pestpac", "webhooks", "gocanvas"],
    "companies",
  );
  const { can } = usePermissions();
  const operator = useOperatorsGetOperator(operatorId);
  useDocumentTitle(operator.data?.data.name);

  if (operator.isPending) return <p className="text-muted-foreground">Loading…</p>;
  if (operator.isError) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{errorMessage(operator.error, "Operator not found.")}</AlertDescription>
      </Alert>
    );
  }
  const op = operator.data.data;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <Breadcrumbs trail={[]} />
        <h1 className="mt-2 flex items-center gap-3 text-3xl">
          {op.name}
          {!op.is_active && <Badge variant="outline">Inactive</Badge>}
        </h1>
        <p className="text-muted-foreground">PestPac tenant {op.pestpac_tenant_id}</p>
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          {can("companies:read", operatorId) && (
            <TabsTrigger value="companies">Companies</TabsTrigger>
          )}
          {can("members:read", operatorId) && <TabsTrigger value="members">Members</TabsTrigger>}
          {can("pestpac_connection:read", operatorId) && (
            <TabsTrigger value="pestpac">PestPac API</TabsTrigger>
          )}
          {can("webhooks:read", operatorId) && <TabsTrigger value="webhooks">Webhooks</TabsTrigger>}
          {can("webhooks:read", operatorId) && <TabsTrigger value="gocanvas">GoCanvas</TabsTrigger>}
        </TabsList>
        {can("companies:read", operatorId) && (
          <TabsContent value="companies" className="pt-4">
            <CompaniesTab operatorId={operatorId} />
          </TabsContent>
        )}
        {can("members:read", operatorId) && (
          <TabsContent value="members" className="pt-4">
            <MembersPanel tenantId={operatorId} roleScope="operator" />
          </TabsContent>
        )}
        {can("pestpac_connection:read", operatorId) && (
          <TabsContent value="pestpac" className="pt-4">
            <PestPacConnectionPanel operatorId={operatorId} />
          </TabsContent>
        )}
        {can("webhooks:read", operatorId) && (
          <TabsContent value="webhooks" className="pt-4">
            <WebhookEventsPanel operatorId={operatorId} />
          </TabsContent>
        )}
        {can("webhooks:read", operatorId) && (
          <TabsContent value="gocanvas" className="pt-4">
            <GoCanvasRequestsPanel operatorId={operatorId} />
          </TabsContent>
        )}
      </Tabs>
    </div>
  );
}
