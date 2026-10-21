"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/api/errors";
import type { PestPacConnectionRead } from "@/lib/api/generated/model";
import {
  getPestpacGetConnectionQueryKey,
  usePestpacGetConnection,
  usePestpacSaveConnection,
  usePestpacVerifyConnection,
} from "@/lib/api/generated/pestpac/pestpac";
import { usePermissions } from "@/lib/permissions";

const SECRET_FIELDS = ["client_secret", "password", "api_key"] as const;

function makeSchema(configured: boolean) {
  // Secrets are required on first setup; afterwards an empty field keeps the stored value.
  const secret = configured ? z.string() : z.string().min(1, "Required for the first setup");
  return z.object({
    client_id: z.string().trim().min(1, "Required").max(255),
    username: z.string().trim().min(1, "Required").max(255),
    client_secret: secret,
    password: secret,
    api_key: secret,
  });
}
type FormValues = z.infer<ReturnType<typeof makeSchema>>;

export function ConnectionStatusBadge({ conn }: { conn: PestPacConnectionRead }) {
  if (!conn.configured) return <Badge variant="outline">Not set up</Badge>;
  if (conn.status === "verified") return <Badge variant="success">Verified</Badge>;
  if (conn.status === "failed") return <Badge variant="destructive">Failed</Badge>;
  return <Badge variant="warning">Not verified</Badge>;
}

function ConnectionForm({ operatorId, conn }: { operatorId: string; conn: PestPacConnectionRead }) {
  const queryClient = useQueryClient();
  const onSaved = (data: { data: PestPacConnectionRead }) =>
    queryClient.setQueryData(getPestpacGetConnectionQueryKey(operatorId), data);
  const save = usePestpacSaveConnection({ mutation: { onSuccess: onSaved } });
  const {
    register,
    handleSubmit,
    resetField,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(makeSchema(conn.configured)),
    values: {
      client_id: conn.client_id ?? "",
      username: conn.username ?? "",
      client_secret: "",
      password: "",
      api_key: "",
    },
  });

  const onSubmit = async (values: FormValues) => {
    await save.mutateAsync({
      operatorId,
      data: {
        client_id: values.client_id,
        username: values.username,
        // Empty secret fields are omitted so the stored values are kept.
        ...Object.fromEntries(
          SECRET_FIELDS.filter((f) => values[f]).map((f) => [f, values[f]]),
        ),
      },
    });
    SECRET_FIELDS.forEach((f) => resetField(f));
  };

  const savedHint = (has: boolean) => (conn.configured && has ? "•••• saved" : undefined);

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="grid gap-4 sm:grid-cols-2" noValidate>
      <div className="flex flex-col gap-2">
        <Label htmlFor="pp-client-id">Client ID</Label>
        <Input id="pp-client-id" autoComplete="off" {...register("client_id")} />
        {errors.client_id && <p className="text-sm text-destructive">{errors.client_id.message}</p>}
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor="pp-client-secret">Client secret</Label>
        <Input
          id="pp-client-secret"
          type="password"
          autoComplete="new-password"
          placeholder={savedHint(conn.has_client_secret ?? false)}
          {...register("client_secret")}
        />
        {errors.client_secret && (
          <p className="text-sm text-destructive">{errors.client_secret.message}</p>
        )}
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor="pp-username">API username</Label>
        <Input id="pp-username" autoComplete="off" {...register("username")} />
        {errors.username && <p className="text-sm text-destructive">{errors.username.message}</p>}
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor="pp-password">API password</Label>
        <Input
          id="pp-password"
          type="password"
          autoComplete="new-password"
          placeholder={savedHint(conn.has_password ?? false)}
          {...register("password")}
        />
        {errors.password && <p className="text-sm text-destructive">{errors.password.message}</p>}
      </div>
      <div className="flex flex-col gap-2 sm:col-span-2">
        <Label htmlFor="pp-api-key">API key</Label>
        <Input
          id="pp-api-key"
          type="password"
          autoComplete="new-password"
          placeholder={conn.api_key_last4 ? `•••• ${conn.api_key_last4}` : undefined}
          {...register("api_key")}
        />
        {errors.api_key && <p className="text-sm text-destructive">{errors.api_key.message}</p>}
        {conn.configured && (
          <p className="text-sm text-muted-foreground">
            Leave secret fields empty to keep the saved values.
          </p>
        )}
      </div>
      <div className="sm:col-span-2">
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? "Saving and testing…" : "Save & test"}
        </Button>
      </div>
      {save.isError && (
        <Alert variant="destructive" className="sm:col-span-2">
          <AlertDescription>{errorMessage(save.error)}</AlertDescription>
        </Alert>
      )}
    </form>
  );
}

export function PestPacConnectionPanel({ operatorId }: { operatorId: string }) {
  const queryClient = useQueryClient();
  const { can } = usePermissions();
  const connection = usePestpacGetConnection(operatorId);
  const verify = usePestpacVerifyConnection({
    mutation: {
      onSuccess: (data) =>
        queryClient.setQueryData(getPestpacGetConnectionQueryKey(operatorId), data),
    },
  });

  if (connection.isPending) return <p className="text-muted-foreground">Loading…</p>;
  if (connection.isError) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{errorMessage(connection.error, "Could not load PestPac access.")}</AlertDescription>
      </Alert>
    );
  }
  const conn = connection.data.data;
  const canWrite = can("pestpac_connection:write", operatorId);

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-3">
            PestPac API access
            <ConnectionStatusBadge conn={conn} />
          </CardTitle>
          <CardDescription>
            Tenant {conn.pestpac_tenant_id}
            {conn.pestpac_company_name &&
              ` · ${conn.pestpac_company_name} (CompanyID ${conn.pestpac_company_id})`}
            {conn.last_verified_at &&
              ` · last tested ${new Date(conn.last_verified_at).toLocaleString()}`}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {conn.status === "failed" && conn.last_error && (
            <Alert variant="destructive">
              <AlertDescription>{conn.last_error}</AlertDescription>
            </Alert>
          )}
          {!conn.configured && (
            <p className="text-sm text-muted-foreground">
              Bill-tos can be onboarded once PestPac API access is set up and verified.
            </p>
          )}
          {canWrite && conn.configured && (
            <div>
              <Button
                variant="outline"
                disabled={verify.isPending}
                onClick={() => verify.mutate({ operatorId })}
              >
                {verify.isPending ? "Testing…" : "Test connection"}
              </Button>
            </div>
          )}
          {verify.isError && (
            <Alert variant="destructive">
              <AlertDescription>{errorMessage(verify.error)}</AlertDescription>
            </Alert>
          )}
        </CardContent>
      </Card>

      {canWrite && (
        <Card>
          <CardHeader>
            <CardTitle>{conn.configured ? "Update credentials" : "Set up credentials"}</CardTitle>
            <CardDescription>
              Stored encrypted. Secrets are never shown again after saving.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ConnectionForm operatorId={operatorId} conn={conn} />
          </CardContent>
        </Card>
      )}
    </div>
  );
}
