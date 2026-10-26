"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Check, CircleX, Clock, LoaderCircle, RefreshCw, TriangleAlert } from "lucide-react";
import { useEffect, useRef } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/api/errors";
import {
  getBillTosListSyncJobsQueryKey,
  useBillTosListSyncJobs,
  useBillTosSyncLocations,
  useBillTosSyncServiceOrders,
} from "@/lib/api/generated/bill-tos/bill-tos";
import {
  useLocationsSyncLocation,
  useLocationsSyncServiceOrders,
} from "@/lib/api/generated/locations/locations";
import type { SyncJobRead } from "@/lib/api/generated/model";

const POLL_MS = 3000;
// A job still queued after this long usually means no worker is running.
const STALE_QUEUE_MS = 30_000;

const isActive = (job: SyncJobRead | undefined) =>
  job?.status === "queued" || job?.status === "running";

type Counts = Record<string, number>;

/** What a panel syncs; each shows only its own kind of job. */
// "location": documents and conditions, and later per-location syncs as they're added.
export type SyncKind = "serviceOrders" | "location";

const JOB_KINDS: Record<SyncKind, readonly string[]> = {
  serviceOrders: ["bill_to_service_orders", "location_service_orders"],
  location: ["bill_to_location_sync", "location_sync"],
};

const TITLE: Record<SyncKind, string> = {
  serviceOrders: "Orders and notes",
  location: "Documents and conditions",
};

/** progress is free-form JSON from the worker; read only the numbers we show. */
function counts(job: SyncJobRead, key: "orders" | "notes" | "documents" | "conditions"): Counts {
  const value = job.progress[key];
  if (typeof value !== "object" || value === null) return {};
  return Object.fromEntries(
    Object.entries(value).filter(
      (entry): entry is [string, number] => typeof entry[1] === "number",
    ),
  );
}

function num(job: SyncJobRead, key: string): number | undefined {
  const value = job.progress[key];
  return typeof value === "number" ? value : undefined;
}

function summary(job: SyncJobRead): string {
  const orders = counts(job, "orders");
  const notes = counts(job, "notes");
  const documents = counts(job, "documents");
  const conditions = counts(job, "conditions");
  const parts = [
    orders.added && `${orders.added} new orders`,
    orders.updated && `${orders.updated} updated`,
    orders.newly_posted && `${orders.newly_posted} newly worked`,
    orders.closed && `${orders.closed} billed`,
    notes.added && `${notes.added} new notes`,
    notes.invoices_found && `${notes.invoices_found} invoices found`,
    documents.added && `${documents.added} new documents`,
    documents.removed && `${documents.removed} removed`,
    documents.files_stored && `${documents.files_stored} files stored`,
    documents.files_failed && `${documents.files_failed} files failed`,
    documents.files_too_large && `${documents.files_too_large} files too large`,
    conditions.added && `${conditions.added} new conditions`,
    conditions.details_fetched && `${conditions.details_fetched} conditions updated`,
    conditions.closed && `${conditions.closed} closed`,
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(", ") : "no changes";
}

// Where a bill-to-wide job records each step's failed locations.
const FAILURE_LISTS = [
  ["failed_locations", null],
  ["notes_failed_locations", "Notes"],
  ["invoices_failed_locations", "Invoices"],
  ["conditions_failed_locations", "Conditions"],
] as const;

/** One location's failures in a bill-to-wide job: the location itself failed (nothing of it
 * synced), or only a later step (notes, invoices, conditions) did. */
function locationFailures(
  job: SyncJobRead,
  pestpacLocationId: number,
): { failed: boolean; errors: string[] } {
  let failed = false;
  const errors: string[] = [];
  for (const [key, step] of FAILURE_LISTS) {
    const list = job.progress[key];
    if (!Array.isArray(list)) continue;
    for (const entry of list) {
      if (typeof entry !== "object" || entry === null) continue;
      const item = entry as { pestpac_location_id?: unknown; error?: unknown };
      if (item.pestpac_location_id !== pestpacLocationId) continue;
      if (step === null) failed = true;
      const error = typeof item.error === "string" ? item.error : "failed";
      errors.push(step ? `${step}: ${error}` : error);
    }
  }
  return { failed, errors };
}

function JobBadge({ status }: { status: SyncJobRead["status"] }) {
  switch (status) {
    case "queued":
      return (
        <Badge variant="pending">
          <Clock aria-hidden />
          Queued
        </Badge>
      );
    case "running":
      return (
        <Badge variant="pending">
          <LoaderCircle aria-hidden className="motion-safe:animate-spin" />
          Syncing
        </Badge>
      );
    case "succeeded":
      return (
        <Badge variant="success">
          <Check aria-hidden />
          Synced
        </Badge>
      );
    case "partial":
      return (
        <Badge variant="warning">
          <TriangleAlert aria-hidden />
          Partly synced
        </Badge>
      );
    case "failed":
      return (
        <Badge variant="destructive">
          <CircleX aria-hidden />
          Failed
        </Badge>
      );
  }
}

/** `checkedAt`: when the job list was last fetched (it polls while a job is active).
 * `pestpacLocationId`: shown on a location's page, where a finished bill-to-wide job is
 * reported for that location only, not with the whole bill-to's totals and failures. */
function JobLine({
  job,
  checkedAt,
  pestpacLocationId,
}: {
  job: SyncJobRead;
  checkedAt: number;
  pestpacLocationId?: number;
}) {
  const total = num(job, "locations_total");
  const done = num(job, "locations_done") ?? 0;
  const queuedFor = checkedAt - new Date(job.created_at).getTime();
  const when = job.finished_at ? new Date(job.finished_at).toLocaleString() : "";
  if (pestpacLocationId !== undefined && job.location_id === null && !isActive(job)) {
    const { failed, errors } = locationFailures(job, pestpacLocationId);
    // A job that failed outright never reached the locations: its own error applies.
    const status: SyncJobRead["status"] =
      job.status === "failed" || failed ? "failed" : errors.length ? "partial" : "succeeded";
    return (
      <div className="flex flex-col gap-2" role="status" aria-live="polite">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <JobBadge status={status} />
          <span className="text-muted-foreground">
            {when}: in the sync of all the bill-to&apos;s locations.
          </span>
        </div>
        {(job.status === "failed" && job.error ? [job.error] : errors).map((error) => (
          <p key={error} className="text-sm text-destructive">
            {error}
          </p>
        ))}
      </div>
    );
  }
  let text: string;
  if (job.status === "queued") {
    text =
      queuedFor > STALE_QUEUE_MS
        ? "Waiting for the background worker. Is it running?"
        : "Waiting to start…";
  } else if (job.status === "running") {
    text = total ? `Syncing location ${Math.min(done + 1, total)} of ${total}…` : "Starting…";
  } else {
    text = `${when}: ${summary(job)}.`;
  }
  return (
    <div className="flex flex-col gap-2" role="status" aria-live="polite">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <JobBadge status={job.status} />
        <span className="text-muted-foreground">{text}</span>
      </div>
      {job.error && job.status !== "running" && (
        <p className="text-sm text-destructive">{job.error}</p>
      )}
      {/* Set when object storage isn't configured: lists synced, files didn't. */}
      {typeof job.progress.document_files === "string" && (
        <p className="text-sm text-muted-foreground">
          Files not stored: {job.progress.document_files}
        </p>
      )}
    </div>
  );
}

/**
 * Sync service orders (and their notes), or documents and conditions, from
 * PestPac for a bill-to or one of its locations.
 * Shows the latest job and polls while it runs; calls `onFinished` when a job completes so the
 * caller can refetch what it displays.
 */
export function SyncJobPanel({
  billToId,
  locationId,
  pestpacLocationId,
  kind = "serviceOrders",
  canSync,
  onFinished,
}: {
  billToId: string;
  locationId?: string;
  /** With `locationId`: its PestPac LocationID, to find it in a bill-to-wide job's results. */
  pestpacLocationId?: number;
  kind?: SyncKind;
  canSync: boolean;
  onFinished: () => void;
}) {
  const queryClient = useQueryClient();
  const jobsKey = getBillTosListSyncJobsQueryKey(billToId);
  // On a location, the API returns its newest job of each kind (its own or bill-to-wide), so
  // syncs queued for other locations can't push it out of the list.
  const jobs = useBillTosListSyncJobs(
    billToId,
    locationId ? { location_id: locationId } : undefined,
    {
      query: {
        refetchInterval: (query) => {
          const list = query.state.data?.data ?? [];
          return list.some((j) => isActive(j)) ? POLL_MS : false;
        },
      },
    },
  );
  // Newest first from the API.
  const latest = jobs.data?.data.find(
    (j) =>
      JOB_KINDS[kind].includes(j.kind) &&
      (locationId ? j.location_id === locationId || j.location_id === null : true),
  );

  const previous = useRef<SyncJobRead | undefined>(undefined);
  useEffect(() => {
    const before = previous.current;
    previous.current = latest;
    if (before && latest && before.id === latest.id && isActive(before) && !isActive(latest)) {
      onFinished();
    }
  }, [latest, onFinished]);

  const onQueued = () => queryClient.invalidateQueries({ queryKey: jobsKey });
  const ordersBillTo = useBillTosSyncServiceOrders({ mutation: { onSuccess: onQueued } });
  const ordersLocation = useLocationsSyncServiceOrders({ mutation: { onSuccess: onQueued } });
  const locationsBillTo = useBillTosSyncLocations({ mutation: { onSuccess: onQueued } });
  const locationOne = useLocationsSyncLocation({ mutation: { onSuccess: onQueued } });
  const [syncBillTo, syncLocation] =
    kind === "location" ? [locationsBillTo, locationOne] : [ordersBillTo, ordersLocation];
  const sync = locationId ? syncLocation : syncBillTo;
  const start = () =>
    locationId ? syncLocation.mutate({ locationId }) : syncBillTo.mutate({ billToId });

  return (
    <div className="flex flex-col gap-2 py-3">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 flex-col gap-1">
          <span className="font-medium">{TITLE[kind]}</span>
          {latest ? (
            <JobLine
              job={latest}
              checkedAt={jobs.dataUpdatedAt}
              pestpacLocationId={pestpacLocationId}
            />
          ) : (
            jobs.isSuccess && (
              <p className="text-sm text-muted-foreground">Not synced from PestPac yet.</p>
            )
          )}
        </div>
        {canSync && (
          <Button
            variant="outline"
            size="sm"
            disabled={sync.isPending || isActive(latest)}
            onClick={start}
            aria-label={`Sync ${TITLE[kind].toLowerCase()}`}
          >
            <RefreshCw aria-hidden />
            {isActive(latest) ? "Syncing…" : "Sync"}
          </Button>
        )}
      </div>
      {sync.isError && (
        <Alert variant="destructive">
          <AlertDescription>{errorMessage(sync.error)}</AlertDescription>
        </Alert>
      )}
      {jobs.isError && (
        <Alert variant="destructive">
          <AlertDescription>
            {errorMessage(jobs.error, "Could not load sync status.")}
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}

/** Both syncs for a bill-to (every location) or one location, under one heading. */
export function PestPacSync({
  billToId,
  locationId,
  pestpacLocationId,
  canSync,
  onOrdersSynced,
  onLocationSynced,
}: {
  billToId: string;
  locationId?: string;
  pestpacLocationId?: number;
  canSync: boolean;
  onOrdersSynced: () => void;
  onLocationSynced: () => void;
}) {
  return (
    <section aria-labelledby="pestpac-sync" className="border border-border bg-card px-4 py-1">
      <h2 id="pestpac-sync" className="sr-only">
        Sync from PestPac
      </h2>
      <div className="divide-y divide-border">
        <SyncJobPanel
          billToId={billToId}
          locationId={locationId}
          pestpacLocationId={pestpacLocationId}
          canSync={canSync}
          onFinished={onOrdersSynced}
        />
        {/* Documents and conditions: on request, never with order syncs. */}
        <SyncJobPanel
          billToId={billToId}
          locationId={locationId}
          pestpacLocationId={pestpacLocationId}
          kind="location"
          canSync={canSync}
          onFinished={onLocationSynced}
        />
      </div>
    </section>
  );
}
