"use client";

import { useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { useEffect, useRef } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/api/errors";
import {
  getBillTosListSyncJobsQueryKey,
  useBillTosListSyncJobs,
  useBillTosSyncServiceOrders,
} from "@/lib/api/generated/bill-tos/bill-tos";
import { useLocationsSyncServiceOrders } from "@/lib/api/generated/locations/locations";
import type { SyncJobRead } from "@/lib/api/generated/model";

const POLL_MS = 3000;
// A job still queued after this long usually means no worker is running.
const STALE_QUEUE_MS = 30_000;

const isActive = (job: SyncJobRead | undefined) =>
  job?.status === "queued" || job?.status === "running";

type Counts = Record<string, number>;

/** progress is free-form JSON from the worker; read only the numbers we show. */
function counts(job: SyncJobRead, key: "orders" | "notes"): Counts {
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
  const parts = [
    orders.added && `${orders.added} new orders`,
    orders.updated && `${orders.updated} updated`,
    orders.newly_posted && `${orders.newly_posted} newly worked`,
    orders.closed && `${orders.closed} billed`,
    notes.added && `${notes.added} new notes`,
    notes.invoices_found && `${notes.invoices_found} invoices found`,
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(", ") : "no changes";
}

function JobBadge({ job }: { job: SyncJobRead }) {
  switch (job.status) {
    case "queued":
      return <Badge variant="outline">Queued</Badge>;
    case "running":
      return <Badge variant="secondary">Syncing</Badge>;
    case "succeeded":
      return <Badge variant="success">Synced</Badge>;
    case "partial":
      return <Badge variant="warning">Partly synced</Badge>;
    case "failed":
      return <Badge variant="destructive">Failed</Badge>;
  }
}

/** `checkedAt`: when the job list was last fetched (it polls while a job is active). */
function JobLine({ job, checkedAt }: { job: SyncJobRead; checkedAt: number }) {
  const total = num(job, "locations_total");
  const done = num(job, "locations_done") ?? 0;
  const queuedFor = checkedAt - new Date(job.created_at).getTime();
  let text: string;
  if (job.status === "queued") {
    text =
      queuedFor > STALE_QUEUE_MS
        ? "Waiting for the background worker. Is it running?"
        : "Waiting to start…";
  } else if (job.status === "running") {
    text = total ? `Syncing location ${Math.min(done + 1, total)} of ${total}…` : "Starting…";
  } else {
    const when = job.finished_at ? new Date(job.finished_at).toLocaleString() : "";
    text = `${when}: ${summary(job)}.`;
  }
  return (
    <div className="flex flex-col gap-2" role="status" aria-live="polite">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <JobBadge job={job} />
        <span className="text-muted-foreground">{text}</span>
      </div>
      {job.error && job.status !== "running" && (
        <p className="text-sm text-destructive">{job.error}</p>
      )}
    </div>
  );
}

/**
 * Sync service orders (and their notes) from PestPac for a bill-to, or one of its locations.
 * Shows the latest job and polls while it runs; calls `onFinished` when a job completes so the
 * caller can refetch what it displays.
 */
export function SyncJobPanel({
  billToId,
  locationId,
  canSync,
  onFinished,
}: {
  billToId: string;
  locationId?: string;
  canSync: boolean;
  onFinished: () => void;
}) {
  const queryClient = useQueryClient();
  const jobsKey = getBillTosListSyncJobsQueryKey(billToId);
  const jobs = useBillTosListSyncJobs(billToId, {
    query: {
      refetchInterval: (query) => {
        const list = query.state.data?.data ?? [];
        return list.some((j) => isActive(j)) ? POLL_MS : false;
      },
    },
  });
  // A location is covered by its own jobs and by bill-to-wide ones (newest first from the API).
  const latest = jobs.data?.data.find((j) =>
    locationId ? j.location_id === locationId || j.location_id === null : true,
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
  const syncBillTo = useBillTosSyncServiceOrders({ mutation: { onSuccess: onQueued } });
  const syncLocation = useLocationsSyncServiceOrders({ mutation: { onSuccess: onQueued } });
  const sync = locationId ? syncLocation : syncBillTo;
  const start = () =>
    locationId ? syncLocation.mutate({ locationId }) : syncBillTo.mutate({ billToId });

  return (
    <div className="flex flex-col gap-3">
      {canSync && (
        <div>
          <Button variant="outline" disabled={sync.isPending || isActive(latest)} onClick={start}>
            <RefreshCw aria-hidden />
            {isActive(latest) ? "Sync in progress" : "Sync service orders"}
          </Button>
        </div>
      )}
      {latest ? (
        <JobLine job={latest} checkedAt={jobs.dataUpdatedAt} />
      ) : (
        jobs.isSuccess && (
          <p className="text-sm text-muted-foreground">Not synced from PestPac yet.</p>
        )
      )}
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
