"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";

import { SenderRows } from "@/components/webhook-events-panel";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/api/errors";
import type { GoCanvasRequestRead } from "@/lib/api/generated/model";
import {
  useWebhooksGetGocanvasRequest,
  useWebhooksListGocanvasRequests,
} from "@/lib/api/generated/webhooks/webhooks";

const PAGE_SIZE = 50;

function formatBody(raw: string, contentType: string | null): string {
  if (contentType?.includes("json")) {
    try {
      return JSON.stringify(JSON.parse(raw), null, 2);
    } catch {
      return raw; // declared JSON but isn't: show it unchanged
    }
  }
  return raw;
}

function RequestDetail({ requestId }: { requestId: string }) {
  const detail = useWebhooksGetGocanvasRequest(requestId);
  if (detail.isPending) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (detail.isError) {
    return (
      <p className="text-sm text-destructive">
        {errorMessage(detail.error, "Could not load the request.")}
      </p>
    );
  }
  const r = detail.data.data;
  return (
    <div className="flex flex-col gap-3">
      <dl className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
        <SenderRows request={r} />
        {r.query_string && (
          <>
            <dt className="text-muted-foreground">Query</dt>
            <dd className="break-all">{r.query_string}</dd>
          </>
        )}
      </dl>
      <details>
        <summary className="cursor-pointer text-sm text-primary hover:underline">
          Headers ({Object.keys(r.headers).length})
        </summary>
        <dl className="mt-2 grid gap-x-6 gap-y-1 text-xs sm:grid-cols-[auto_1fr]">
          {Object.entries(r.headers).map(([name, value]) => (
            <div key={name} className="contents">
              <dt className="font-mono text-muted-foreground">{name}</dt>
              <dd className="font-mono break-all">{value}</dd>
            </div>
          ))}
        </dl>
      </details>
      {r.raw_body !== null ? (
        r.body_size > 0 ? (
          <pre className="max-h-96 overflow-auto rounded-lg border border-border bg-muted p-3 text-xs">
            {formatBody(r.raw_body, r.content_type)}
          </pre>
        ) : (
          <p className="text-sm text-muted-foreground">Empty body.</p>
        )
      ) : (
        <p className="text-sm text-muted-foreground">
          Body cleared
          {r.raw_body_purged_at &&
            ` on ${new Date(r.raw_body_purged_at).toLocaleDateString()}`}{" "}
          after the retention period.
        </p>
      )}
    </div>
  );
}

function RequestRow({ request: r }: { request: GoCanvasRequestRead }) {
  const [expanded, setExpanded] = useState(false);
  const panelId = `gocanvas-${r.id}`;
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
        <Badge variant="outline">{r.method}</Badge>
        <span className="text-sm">{r.content_type ?? "No content type"}</span>
        <span className="text-sm text-muted-foreground">
          {r.body_size.toLocaleString()} bytes · {r.client_ip ?? "unknown IP"}
        </span>
        <span className="ml-auto text-sm text-muted-foreground">
          {new Date(r.received_at).toLocaleString(undefined, {
            dateStyle: "medium",
            timeStyle: "medium",
          })}
        </span>
      </button>
      {expanded && (
        <div id={panelId} className="mt-3 border-l-2 border-border pl-4">
          <RequestDetail requestId={r.id} />
        </div>
      )}
    </li>
  );
}

/** Requests received at the operator's GoCanvas webhook URL (stored as received). */
export function GoCanvasRequestsPanel({ operatorId }: { operatorId: string }) {
  const [offset, setOffset] = useState(0);
  const requests = useWebhooksListGocanvasRequests(operatorId, { limit: PAGE_SIZE, offset });
  const page = requests.data?.data;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1 text-sm">
        <p>
          GoCanvas sends requests to{" "}
          <code className="rounded bg-muted px-1 py-0.5 break-all">
            /v1/webhooks/gocanvas/{operatorId}
          </code>{" "}
          on the API host (not this web app).
        </p>
        <p className="text-muted-foreground">
          Every request is stored as received (headers without credentials, body, sender IP and user
          agent) until GoCanvas&apos;s format is known. Nothing is processed yet.
        </p>
      </div>
      {requests.isPending && <p className="text-muted-foreground">Loading…</p>}
      {requests.isError && (
        <Alert variant="destructive">
          <AlertDescription>
            {errorMessage(requests.error, "Could not load GoCanvas requests.")}
          </AlertDescription>
        </Alert>
      )}
      {page && (
        <>
          <ul className="divide-y divide-border border border-border bg-card">
            {page.items.length === 0 && (
              <li className="p-4 text-muted-foreground">No requests received yet.</li>
            )}
            {page.items.map((r) => (
              <RequestRow key={r.id} request={r} />
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
