"use client";

import { useState } from "react";

import { InvoiceRow } from "@/components/location-invoices";
import { OrderRow } from "@/components/service-order-list";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { errorMessage } from "@/lib/api/errors";
import {
  useInvoicesListBillToInvoicedOrders,
  useInvoicesListCompanyInvoicedOrders,
} from "@/lib/api/generated/invoices/invoices";
import type { InvoicedOrderPage } from "@/lib/api/generated/model";

const PAGE_SIZE = 50;

function InvoicedOrderList({
  query,
  offset,
  setOffset,
}: {
  query: {
    isPending: boolean;
    isError: boolean;
    error: unknown;
    data?: { data: InvoicedOrderPage };
  };
  offset: number;
  setOffset: (offset: number) => void;
}) {
  if (query.isPending) return <p className="text-muted-foreground">Loading…</p>;
  if (query.isError || !query.data) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{errorMessage(query.error, "Could not load invoices.")}</AlertDescription>
      </Alert>
    );
  }
  const page = query.data.data;
  return (
    <div className="flex flex-col gap-3">
      <ul className="divide-y divide-border border border-border bg-card">
        {page.items.length === 0 && (
          <li className="p-4 text-muted-foreground">No invoices recorded yet.</li>
        )}
        {page.items.map((item) => (
          <InvoiceRow
            key={item.id}
            invoice={item}
            location={item.location_id ? { id: item.location_id, name: item.location_name } : null}
          >
            <div className="mt-3">
              <div className="mb-1 text-xs font-medium text-muted-foreground">Service order</div>
              {item.service_order ? (
                <ul className="border border-border bg-muted/40">
                  <OrderRow order={item.service_order} showLocation={false} />
                </ul>
              ) : (
                <p className="text-sm text-muted-foreground">
                  {item.pestpac_order_id
                    ? `OrderID ${item.pestpac_order_id} isn't synced to the portal.`
                    : "Not linked to a service order."}
                </p>
              )}
            </div>
          </InvoiceRow>
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
    </div>
  );
}

/** Invoices for a bill-to or a whole company, newest first, each with the order it bills. */
export function InvoicedOrders(props: { billToId: string } | { companyId: string }) {
  const [offset, setOffset] = useState(0);
  const params = { limit: PAGE_SIZE, offset };
  const isBillTo = "billToId" in props;
  const billTo = useInvoicesListBillToInvoicedOrders(isBillTo ? props.billToId : "", params, {
    query: { enabled: isBillTo },
  });
  const company = useInvoicesListCompanyInvoicedOrders(isBillTo ? "" : props.companyId, params, {
    query: { enabled: !isBillTo },
  });
  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-muted-foreground">
        Invoices from PestPac, newest first, with the service order each one bills.
      </p>
      <InvoicedOrderList
        query={isBillTo ? billTo : company}
        offset={offset}
        setOffset={setOffset}
      />
    </div>
  );
}
