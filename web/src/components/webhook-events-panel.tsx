"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { errorMessage } from "@/lib/api/errors";
import {
  SignatureStatus,
  WebhookEntity,
  type WebhookEventRead,
  WebhookEventStatus,
} from "@/lib/api/generated/model";
import { usePestpacGetConnection } from "@/lib/api/generated/pestpac/pestpac";
import {
  useWebhooksGetWebhookEvent,
  useWebhooksListWebhookEvents,
} from "@/lib/api/generated/webhooks/webhooks";
import { usePermissions } from "@/lib/permissions";

const PAGE_SIZE = 50;

const ENTITY_LABELS: Record<WebhookEntity, string> = {
  bill_to: "Bill-to",
  employee: "Employee",
  invoice: "Invoice",
  location: "Location",
  note: "Note",
  service_order: "Service order",
};

const SIGNATURE_LABELS: Record<SignatureStatus, string> = {
  valid: "Signature valid",
  invalid: "Signature invalid",
  missing: "No signature",
  no_secret: "No secret set",
};

function SignatureBadge({ status }: { status: SignatureStatus }) {
  const variant = status === "valid" ? "success" : status === "invalid" ? "destructive" : "outline";
  return <Badge variant={variant}>{SIGNATURE_LABELS[status]}</Badge>;
}

function StatusBadge({ status }: { status: WebhookEventStatus }) {
  if (status === "failed") return <Badge variant="destructive">Failed</Badge>;
  if (status === "processed") return <Badge variant="success">Processed</Badge>;
  return <Badge variant="pending">Received</Badge>;
}

/** Pretty-prints a JSON body; shows it as sent if it doesn't parse. */
function formatBody(raw: string): string {
  try {
    return JSON.stringify(JSON.parse(raw), null, 2);
  } catch {
    // Stored bodies passed envelope parsing, so this is unexpected; show the text unchanged.
    return raw;
  }
}

/** Who sent a webhook request (definition-list rows). */
export function SenderRows({
  request: r,
}: {
  request: { client_ip: string | null; forwarded_for: string | null; user_agent: string | null };
}) {
  return (
    <>
      <dt className="text-muted-foreground">Sender IP</dt>
      <dd>
        {r.client_ip ?? "Unknown"}
        {r.forwarded_for && (
          <span className="text-muted-foreground">
            {" "}
            · forwarded for {r.forwarded_for} (unverified)
          </span>
        )}
      </dd>
      <dt className="text-muted-foreground">User agent</dt>
      <dd className="break-all">{r.user_agent ?? "Not sent"}</dd>
    </>
  );
}

function EventDetail({ eventId }: { eventId: string }) {
  const detail = useWebhooksGetWebhookEvent(eventId);
  if (detail.isPending) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (detail.isError) {
    return (
      <p className="text-sm text-destructive">
        {errorMessage(detail.error, "Could not load the event.")}
      </p>
    );
  }
  const e = detail.data.data;
  return (
    <div className="flex flex-col gap-3">
      <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
        <dt className="text-muted-foreground">PestPac timestamp</dt>
        <dd>{e.pestpac_timestamp ?? "Not sent"}</dd>
        {e.pestpac_bill_to_id !== null && (
          <>
            <dt className="text-muted-foreground">BillToID</dt>
            <dd>
              {e.bill_to_id ? (
                <Link href={`/bill-tos/${e.bill_to_id}`} className="text-primary hover:underline">
                  {e.pestpac_bill_to_id}
                </Link>
              ) : (
                e.pestpac_bill_to_id
              )}
            </dd>
          </>
        )}
        {e.pestpac_location_id !== null && (
          <>
            <dt className="text-muted-foreground">LocationID</dt>
            <dd>
              {e.location_id ? (
                <Link href={`/locations/${e.location_id}`} className="text-primary hover:underline">
                  {e.pestpac_location_id}
                </Link>
              ) : (
                e.pestpac_location_id
              )}
            </dd>
          </>
        )}
        <SenderRows request={e} />
        {e.error && (
          <>
            <dt className="text-muted-foreground">Error</dt>
            <dd className="text-destructive">{e.error}</dd>
          </>
        )}
      </dl>
      {e.raw_body !== null ? (
        <pre className="max-h-96 overflow-auto rounded-lg border border-border bg-muted p-3 text-xs">
          {formatBody(e.raw_body)}
        </pre>
      ) : (
        <p className="text-sm text-muted-foreground">
          Body cleared
          {e.raw_body_purged_at &&
            ` on ${new Date(e.raw_body_purged_at).toLocaleDateString()}`}{" "}
          after the retention period.
        </p>
      )}
    </div>
  );
}

function EventRow({ event }: { event: WebhookEventRead }) {
  const [expanded, setExpanded] = useState(false);
  const panelId = `webhook-${event.id}`;
  return (
    <li className="p-4">
      <button
        type="button"
        aria-expanded={expanded}
        aria-controls={panelId}
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full flex-wrap items-center gap-2 text-left"
      >
        {expanded ? (
          <ChevronDown className="size-4 text-muted-foreground" aria-hidden />
        ) : (
          <ChevronRight className="size-4 text-muted-foreground" aria-hidden />
        )}
        <span className="font-medium">
          {ENTITY_LABELS[event.entity]} {event.action}
        </span>
        <span className="text-sm text-muted-foreground">#{event.pestpac_entity_id}</span>
        <StatusBadge status={event.status} />
        <SignatureBadge status={event.signature_status} />
        <span className="ml-auto text-sm text-muted-foreground">
          {new Date(event.received_at).toLocaleString(undefined, {
            dateStyle: "medium",
            timeStyle: "medium",
          })}
        </span>
      </button>
      {expanded && (
        <div id={panelId} className="mt-3 border-l-2 border-border pl-4">
          <EventDetail eventId={event.id} />
        </div>
      )}
    </li>
  );
}

function WebhookSetup({ operatorId }: { operatorId: string }) {
  const { can } = usePermissions();
  const canReadConnection = can("pestpac_connection:read", operatorId);
  const connection = usePestpacGetConnection(operatorId, {
    query: { enabled: canReadConnection },
  });
  const hasSecret = connection.data?.data.has_webhook_secret;
  return (
    <div className="flex flex-col gap-1 text-sm">
      <p>
        PestPac sends deliveries to{" "}
        <code className="rounded bg-muted px-1 py-0.5">POST /v1/webhooks/pestpac</code> on the API
        host (not this web app).
      </p>
      {canReadConnection && connection.data && (
        <p className="text-muted-foreground">
          {hasSecret
            ? "A webhook secret is set; signatures are checked and recorded, not enforced."
            : "No webhook secret is set, so signatures can't be checked. Add one under PestPac API."}
        </p>
      )}
      <p className="text-muted-foreground">
        Only deliveries for onboarded bill-tos (and technicians) are stored; the rest are dropped
        and don&apos;t appear here.
      </p>
    </div>
  );
}

export function WebhookEventsPanel({ operatorId }: { operatorId: string }) {
  const [entity, setEntity] = useState<WebhookEntity | "">("");
  const [status, setStatus] = useState<WebhookEventStatus | "">("");
  const [signature, setSignature] = useState<SignatureStatus | "">("");
  const [entityId, setEntityId] = useState("");
  const [offset, setOffset] = useState(0);
  const events = useWebhooksListWebhookEvents(operatorId, {
    entity_id: entityId ? Number(entityId) : undefined,
    entity: entity || undefined,
    status: status || undefined,
    signature_status: signature || undefined,
    limit: PAGE_SIZE,
    offset,
  });
  // Changing a filter starts again from the first page.
  const filter =
    <T,>(set: (v: T) => void) =>
    (v: T) => {
      set(v);
      setOffset(0);
    };

  const page = events.data?.data;
  return (
    <div className="flex flex-col gap-4">
      <WebhookSetup operatorId={operatorId} />
      <div className="flex flex-wrap gap-3">
        <Input
          type="search"
          inputMode="numeric"
          aria-label="EntityId"
          placeholder="EntityId"
          className="h-8 w-36"
          value={entityId}
          // PestPac ids are positive integers; ignore anything else typed.
          onChange={(e) =>
            filter(setEntityId)(e.target.value.replace(/\D/g, "").replace(/^0+/, ""))
          }
        />
        <NativeSelect
          size="sm"
          aria-label="Entity"
          value={entity}
          onChange={(e) => filter(setEntity)(e.target.value as WebhookEntity | "")}
        >
          <NativeSelectOption value="">All entities</NativeSelectOption>
          {Object.values(WebhookEntity).map((v) => (
            <NativeSelectOption key={v} value={v}>
              {ENTITY_LABELS[v]}
            </NativeSelectOption>
          ))}
        </NativeSelect>
        <NativeSelect
          size="sm"
          aria-label="Status"
          value={status}
          onChange={(e) => filter(setStatus)(e.target.value as WebhookEventStatus | "")}
        >
          <NativeSelectOption value="">All statuses</NativeSelectOption>
          {Object.values(WebhookEventStatus).map((v) => (
            <NativeSelectOption key={v} value={v}>
              {v[0].toUpperCase() + v.slice(1)}
            </NativeSelectOption>
          ))}
        </NativeSelect>
        <NativeSelect
          size="sm"
          aria-label="Signature"
          value={signature}
          onChange={(e) => filter(setSignature)(e.target.value as SignatureStatus | "")}
        >
          <NativeSelectOption value="">All signatures</NativeSelectOption>
          {Object.values(SignatureStatus).map((v) => (
            <NativeSelectOption key={v} value={v}>
              {SIGNATURE_LABELS[v]}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      </div>

      {events.isPending && <p className="text-muted-foreground">Loading…</p>}
      {events.isError && (
        <Alert variant="destructive">
          <AlertDescription>
            {errorMessage(events.error, "Could not load webhook events.")}
          </AlertDescription>
        </Alert>
      )}
      {page && (
        <>
          <ul className="divide-y divide-border border border-border bg-card">
            {page.items.length === 0 && (
              <li className="p-4 text-muted-foreground">No webhook events received.</li>
            )}
            {page.items.map((event) => (
              <EventRow key={event.id} event={event} />
            ))}
          </ul>
          {page.total > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
              <span className="text-muted-foreground">
                {page.offset + 1}–{page.offset + page.items.length} of {page.total}
              </span>
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                >
                  Newer
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={page.offset + page.items.length >= page.total}
                  onClick={() => setOffset(offset + PAGE_SIZE)}
                >
                  Older
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
