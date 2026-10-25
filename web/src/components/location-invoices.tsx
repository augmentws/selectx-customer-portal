"use client";

import Link from "next/link";
import { useState } from "react";

import { formatPestPacDate } from "@/components/service-order-list";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/api/errors";
import { useInvoicesListLocationInvoices } from "@/lib/api/generated/invoices/invoices";
import type { InvoiceRead } from "@/lib/api/generated/model";

const PAGE_SIZE = 25;

const money = new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" });

/** Amounts arrive as decimal strings. */
function formatMoney(value: string | null): string {
  return value === null ? "—" : money.format(Number(value));
}

export function InvoiceRow({
  invoice: i,
  location,
  children,
}: {
  invoice: InvoiceRead;
  /** Shown in lists spanning locations. */
  location?: { id: string; name: string | null } | null;
  /** Rendered below the invoice (e.g. its service order). */
  children?: React.ReactNode;
}) {
  return (
    <li className="p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">Invoice {i.invoice_number ?? i.pestpac_invoice_id}</span>
        {i.removed_at && <Badge variant="outline">Deleted in PestPac</Badge>}
        {location && (
          <Link href={`/locations/${location.id}`} className="text-sm text-primary hover:underline">
            {location.name ?? `LocationID ${i.pestpac_location_id}`}
          </Link>
        )}
        {i.balance !== null && Number(i.balance) !== 0 && (
          <Badge variant="warning">Balance {formatMoney(i.balance)}</Badge>
        )}
      </div>
      <div className="mt-1 grid gap-x-6 text-sm sm:grid-cols-3">
        <span>
          {formatPestPacDate(i.invoice_date) || "No invoice date"}
          <br />
          <span className="text-muted-foreground">
            Worked {formatPestPacDate(i.work_date, true) || "—"}
          </span>
        </span>
        <span>
          {i.service_code ?? "—"}
          {i.description && (
            <>
              <br />
              <span className="text-muted-foreground">{i.description}</span>
            </>
          )}
        </span>
        <span>
          Total {formatMoney(i.total)}
          <br />
          <span className="text-muted-foreground">
            Order {i.order_number ?? "—"}
            {i.technician_name && ` · ${i.technician_name}`}
          </span>
        </span>
      </div>
      <details className="mt-2">
        <summary className="cursor-pointer text-sm text-primary hover:underline">
          Lines and details
        </summary>
        <div className="mt-2 flex flex-col gap-3 border-l-2 border-border pl-4 text-sm">
          {i.lines.length > 0 && (
            <table className="w-full text-left">
              <thead className="text-xs text-muted-foreground">
                <tr>
                  <th className="font-medium">Service</th>
                  <th className="text-right font-medium">Qty</th>
                  <th className="text-right font-medium">Unit price</th>
                  <th className="text-right font-medium">Amount</th>
                </tr>
              </thead>
              <tbody>
                {i.lines.map((line) => (
                  <tr key={line.position}>
                    <td>
                      {line.service_code ?? "—"}
                      {line.description && (
                        <span className="text-muted-foreground"> · {line.description}</span>
                      )}
                    </td>
                    <td className="text-right">{line.quantity ?? "—"}</td>
                    <td className="text-right">{formatMoney(line.unit_price)}</td>
                    <td className="text-right">{formatMoney(line.extended_price)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <dl className="grid gap-x-6 gap-y-1 sm:grid-cols-3">
            <div>
              <dt className="text-xs text-muted-foreground">Due</dt>
              <dd>{formatPestPacDate(i.due_date) || "—"}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Cost</dt>
              <dd>{formatMoney(i.cost)}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Time range · duration</dt>
              <dd>
                {i.time_range ?? "—"}
                {i.duration !== null && ` · ${i.duration} min`}
              </dd>
            </div>
          </dl>
          {i.technician_comment && (
            <div>
              <div className="text-xs text-muted-foreground">Technician comment</div>
              <p className="whitespace-pre-line">{i.technician_comment}</p>
            </div>
          )}
        </div>
      </details>
      {children}
    </li>
  );
}

/** The location's PestPac invoices (billing:read). */
export function LocationInvoices({ locationId }: { locationId: string }) {
  const [offset, setOffset] = useState(0);
  const invoices = useInvoicesListLocationInvoices(locationId, { limit: PAGE_SIZE, offset });
  const page = invoices.data?.data;
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-xl">Invoices{page && ` (${page.total})`}</h2>
      {invoices.isPending && <p className="text-muted-foreground">Loading…</p>}
      {invoices.isError && (
        <Alert variant="destructive">
          <AlertDescription>
            {errorMessage(invoices.error, "Could not load invoices.")}
          </AlertDescription>
        </Alert>
      )}
      {page && (
        <>
          <ul className="divide-y divide-border border border-border bg-card">
            {page.items.length === 0 && (
              <li className="p-4 text-muted-foreground">
                No invoices yet. They arrive with PestPac invoice webhooks and order syncs.
              </li>
            )}
            {page.items.map((invoice) => (
              <InvoiceRow key={invoice.id} invoice={invoice} />
            ))}
          </ul>
          {page.total > PAGE_SIZE && (
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
    </section>
  );
}
