"use client";

import { FileText } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { errorMessage } from "@/lib/api/errors";
import type { ReportTemplateRead } from "@/lib/api/generated/model";
import {
  useReportsCreateServiceReport,
  useReportsListReportTemplates,
} from "@/lib/api/generated/reports/reports";
import { usePermissions } from "@/lib/permissions";

/** Service report templates (those with report fields) the user may start from; empty when
 * they can't start reports. */
export function useServiceReportTemplates(
  companyId: string | undefined,
  operatorId: string | undefined,
): ReportTemplateRead[] {
  const { can } = usePermissions();
  const canStart = operatorId !== undefined && can("reports:write", operatorId);
  const templates = useReportsListReportTemplates(companyId ?? "", undefined, {
    query: { enabled: canStart && companyId !== undefined },
  });
  return canStart ? (templates.data?.data.filter((t) => t.fields.length > 0) ?? []) : [];
}

/** Open the order's report, or start one (an order has one report; changes are versions). */
export function ReportAction({
  orderId,
  locationId,
  reportId,
  templates,
}: {
  orderId: string;
  locationId: string | null;
  reportId: string | null | undefined;
  templates: ReportTemplateRead[];
}) {
  const router = useRouter();
  const [templateId, setTemplateId] = useState("");
  const create = useReportsCreateServiceReport({
    mutation: { onSuccess: (res) => router.push(`/service-reports/${res.data.id}`) },
  });
  if (reportId) {
    return (
      <Link
        href={`/service-reports/${reportId}`}
        className={buttonVariants({ variant: "ghost", size: "sm" })}
      >
        <FileText aria-hidden />
        Open report
      </Link>
    );
  }
  if (templates.length === 0 || !locationId) return null;
  const chosen = templateId || templates[0].id;
  return (
    <>
      {templates.length > 1 && (
        <NativeSelect
          size="sm"
          aria-label="Report template"
          value={chosen}
          onChange={(e) => setTemplateId(e.target.value)}
        >
          {templates.map((t) => (
            <NativeSelectOption key={t.id} value={t.id}>
              {t.name}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      )}
      <Button
        variant="outline"
        size="sm"
        disabled={create.isPending}
        onClick={() =>
          create.mutate({ locationId, data: { template_id: chosen, service_order_id: orderId } })
        }
      >
        <FileText aria-hidden />
        {create.isPending ? "Starting…" : "Start report"}
      </Button>
      {create.isError && (
        <span className="text-sm text-destructive">{errorMessage(create.error)}</span>
      )}
    </>
  );
}
