"use client";

import Link from "next/link";
import { useState } from "react";

import { NoteList } from "@/components/note-list";
import { Badge } from "@/components/ui/badge";
import { errorMessage } from "@/lib/api/errors";
import type { ServiceOrderRead } from "@/lib/api/generated/model";
import { useServiceOrdersListNotes } from "@/lib/api/generated/service-orders/service-orders";

/** PestPac sends work dates as local wall-clock time without an offset; show them as-is. */
export function formatPestPacDate(value: string | null, withTime = false): string {
  if (!value) return "";
  const date = new Date(value);
  return withTime
    ? date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })
    : date.toLocaleDateString(undefined, { dateStyle: "medium" });
}

function OrderStatusBadge({ order }: { order: ServiceOrderRead }) {
  if (order.closed_at) return <Badge variant="outline">Billed</Badge>;
  if (order.posted) return <Badge variant="success">Worked</Badge>;
  return <Badge variant="pending">Open</Badge>;
}

function OrderNotes({ orderId }: { orderId: string }) {
  const notes = useServiceOrdersListNotes(orderId);
  if (notes.isPending) return <p className="text-sm text-muted-foreground">Loading notes…</p>;
  if (notes.isError) {
    return (
      <p className="text-sm text-destructive">
        {errorMessage(notes.error, "Could not load notes.")}
      </p>
    );
  }
  return <NoteList notes={notes.data.data} empty="No notes linked to this order yet." compact />;
}

function Instructions({ label, text }: { label: string; text: string | null }) {
  if (!text) return null;
  return (
    <div>
      <dt className="text-xs font-medium text-muted-foreground">{label}</dt>
      <dd className="text-sm whitespace-pre-line">{text}</dd>
    </div>
  );
}

export function OrderRow({
  order,
  locationName,
  showLocation = true,
  actions,
  compact = false,
}: {
  order: ServiceOrderRead;
  locationName?: string;
  /** Shown at the right of the order's heading. */
  actions?: React.ReactNode;
  /** Off when the order is already listed under its location. */
  showLocation?: boolean;
  /** Two lines (for long lists): the order and its location, then date, service, and
   * technician. Instructions and notes stay behind the disclosure either way. */
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const hasInstructions =
    order.location_instructions ||
    order.service_instructions ||
    order.order_instructions ||
    order.technician_comment;
  return (
    <li className="p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">Order {order.order_number ?? order.pestpac_order_id}</span>
        <OrderStatusBadge order={order} />
        {compact && showLocation && order.location_id && (
          <Link
            href={`/locations/${order.location_id}`}
            className="text-sm text-primary hover:underline"
          >
            {locationName ?? `LocationID ${order.pestpac_location_id}`}
          </Link>
        )}
        {order.pestpac_invoice_id !== null && (
          <span className="text-sm text-muted-foreground">Invoice {order.pestpac_invoice_id}</span>
        )}
        {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
      </div>
      {compact ? (
        <p className="mt-1 text-sm text-muted-foreground">
          {[
            formatPestPacDate(order.work_date, true) || "No work date",
            order.service_code,
            order.technician_name ?? "No technician",
          ]
            .filter(Boolean)
            .join(" · ")}
        </p>
      ) : (
        <div className="mt-1 grid gap-x-6 text-sm sm:grid-cols-3">
          <span>
            {formatPestPacDate(order.work_date, true) || "No work date"}
            {order.service_code && (
              <>
                <br />
                <span className="text-muted-foreground">{order.service_code}</span>
              </>
            )}
          </span>
          <span>
            {order.technician_name ?? "No technician"}
            {order.description && (
              <>
                <br />
                <span className="text-muted-foreground">{order.description}</span>
              </>
            )}
          </span>
          <span className="text-muted-foreground">
            {!showLocation ? null : order.location_id ? (
              <Link
                href={`/locations/${order.location_id}`}
                className="text-primary hover:underline"
              >
                {locationName ?? `LocationID ${order.pestpac_location_id}`}
              </Link>
            ) : (
              `LocationID ${order.pestpac_location_id}`
            )}
            {showLocation && <br />}
            OrderID {order.pestpac_order_id}
          </span>
        </div>
      )}
      <details className="mt-2" onToggle={(e) => setOpen(e.currentTarget.open)}>
        <summary className="cursor-pointer text-sm text-primary hover:underline">
          {hasInstructions ? "Instructions and notes" : "Notes"}
        </summary>
        <div className="mt-2 flex flex-col gap-3 border-l-2 border-border pl-4">
          {hasInstructions && (
            <dl className="flex flex-col gap-2">
              <Instructions label="Location instructions" text={order.location_instructions} />
              <Instructions label="Service instructions" text={order.service_instructions} />
              <Instructions label="Order instructions" text={order.order_instructions} />
              <Instructions label="Technician comment" text={order.technician_comment} />
            </dl>
          )}
          {/* Fetched only once opened. */}
          {open && <OrderNotes orderId={order.id} />}
        </div>
      </details>
    </li>
  );
}
