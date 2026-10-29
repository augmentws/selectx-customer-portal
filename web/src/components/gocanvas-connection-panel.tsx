"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, XCircle } from "lucide-react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { ConnectionStatusBadge } from "@/components/pestpac-connection-panel";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { errorMessage } from "@/lib/api/errors";
import {
  getGocanvasGetConnectionQueryKey,
  useGocanvasGetConnection,
  useGocanvasSaveConnection,
  useGocanvasVerifyConnection,
} from "@/lib/api/generated/gocanvas/gocanvas";
import type { GoCanvasConnectionRead } from "@/lib/api/generated/model";
import { usePermissions } from "@/lib/permissions";

function makeSchema(configured: boolean) {
  // The secret is required on first setup; afterwards an empty field keeps the stored value.
  return z.object({
    client_id: z.string().trim().min(1, "Required").max(255),
    client_secret: configured
      ? z.string().max(1024)
      : z.string().min(1, "Required for the first setup").max(1024),
  });
}
type FormValues = z.infer<ReturnType<typeof makeSchema>>;

/** The outcome of a save or test, shown next to the button that triggered it. */
function ConnectionResult({ conn }: { conn: GoCanvasConnectionRead }) {
  if (conn.status === "verified") {
    return (
      <Alert variant="success" role="status">
        <CheckCircle2 aria-hidden />
        <AlertDescription>GoCanvas accepted the credentials.</AlertDescription>
      </Alert>
    );
  }
  return (
    <Alert variant="destructive" role="alert">
      <XCircle aria-hidden />
      <AlertDescription>
        Saved, but the connection test failed: {conn.last_error ?? "unknown error"}
      </AlertDescription>
    </Alert>
  );
}

function ConnectionForm({
  operatorId,
  conn,
}: {
  operatorId: string;
  conn: GoCanvasConnectionRead;
}) {
  const queryClient = useQueryClient();
  const save = useGocanvasSaveConnection({
    mutation: {
      onSuccess: (data) =>
        queryClient.setQueryData(getGocanvasGetConnectionQueryKey(operatorId), data),
    },
  });
  const {
    register,
    handleSubmit,
    resetField,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(makeSchema(conn.configured)),
    values: { client_id: conn.client_id ?? "", client_secret: "" },
  });

  const onSubmit = async (values: FormValues) => {
    await save.mutateAsync({
      operatorId,
      data: {
        client_id: values.client_id,
        // An empty secret is omitted so the stored one is kept.
        ...(values.client_secret ? { client_secret: values.client_secret } : {}),
      },
    });
    resetField("client_secret");
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="grid gap-4 sm:grid-cols-2" noValidate>
      <div className="flex flex-col gap-2">
        <Label htmlFor="gc-client-id">Client ID</Label>
        <Input id="gc-client-id" autoComplete="off" {...register("client_id")} />
        {errors.client_id && <p className="text-sm text-destructive">{errors.client_id.message}</p>}
      </div>
      <div className="flex flex-col gap-2">
        <Label htmlFor="gc-client-secret">Client secret</Label>
        <Input
          id="gc-client-secret"
          type="password"
          autoComplete="new-password"
          placeholder={conn.configured && conn.has_client_secret ? "•••• saved" : undefined}
          {...register("client_secret")}
        />
        {errors.client_secret && (
          <p className="text-sm text-destructive">{errors.client_secret.message}</p>
        )}
      </div>
      {conn.configured && (
        <p className="text-sm text-muted-foreground sm:col-span-2">
          Leave the secret empty to keep the saved value.
        </p>
      )}
      <div className="sm:col-span-2">
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? "Saving and testing…" : "Save & test"}
        </Button>
      </div>
      {save.isSuccess && (
        <div className="sm:col-span-2">
          <ConnectionResult conn={save.data.data} />
        </div>
      )}
      {save.isError && (
        <Alert variant="destructive" className="sm:col-span-2">
          <AlertDescription>{errorMessage(save.error)}</AlertDescription>
        </Alert>
      )}
    </form>
  );
}

export function GoCanvasConnectionPanel({ operatorId }: { operatorId: string }) {
  const queryClient = useQueryClient();
  const { can } = usePermissions();
  const connection = useGocanvasGetConnection(operatorId);
  const verify = useGocanvasVerifyConnection({
    mutation: {
      onSuccess: (data) =>
        queryClient.setQueryData(getGocanvasGetConnectionQueryKey(operatorId), data),
    },
  });

  if (connection.isPending) return <p className="text-muted-foreground">Loading…</p>;
  if (connection.isError) {
    return (
      <Alert variant="destructive">
        <AlertDescription>
          {errorMessage(connection.error, "Could not load GoCanvas access.")}
        </AlertDescription>
      </Alert>
    );
  }
  const conn = connection.data.data;
  const canWrite = can("gocanvas_connection:write", operatorId);

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-3">
            GoCanvas API access
            <ConnectionStatusBadge conn={conn} />
          </CardTitle>
          <CardDescription>
            OAuth client credentials
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
              Inspection submissions can be fetched from GoCanvas once API access is set up and
              verified.
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
          {verify.isSuccess && verify.data.data.status === "verified" && (
            <ConnectionResult conn={verify.data.data} />
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
              Stored encrypted. The client secret is never shown again after saving.
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
