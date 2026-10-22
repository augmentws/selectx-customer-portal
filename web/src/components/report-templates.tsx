"use client";

import { FileDown } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { errorMessage } from "@/lib/api/errors";
import type { ReportTemplateRead } from "@/lib/api/generated/model";
import {
  getReportsGenerateReportUrl,
  useReportsListReportTemplates,
} from "@/lib/api/generated/reports/reports";
import { fetchPdf, saveBlob } from "@/lib/api/pdf";
import { usePermissions } from "@/lib/permissions";

/** The company page's list of its report templates. Authors also see inactive ones. */
export function ReportTemplatesSection({
  companyId,
  operatorId,
}: {
  companyId: string;
  operatorId: string;
}) {
  const { can } = usePermissions();
  const canWrite = can("report_templates:write", operatorId);
  const templates = useReportsListReportTemplates(companyId, { include_inactive: canWrite });

  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl">Report templates</h2>
        {canWrite && (
          <Link
            href={`/companies/${companyId}/report-templates/new`}
            className={buttonVariants({ variant: "outline", size: "sm" })}
          >
            New template
          </Link>
        )}
      </div>
      {templates.isPending && <p className="text-muted-foreground">Loading…</p>}
      {templates.isError && (
        <Alert variant="destructive">
          <AlertDescription>
            {errorMessage(templates.error, "Could not load report templates.")}
          </AlertDescription>
        </Alert>
      )}
      {templates.data && (
        <ul className="divide-y divide-border rounded-lg border border-border bg-card">
          {templates.data.data.length === 0 && (
            <li className="p-4 text-muted-foreground">No report templates for this company yet.</li>
          )}
          {templates.data.data.map((t) => (
            <li key={t.id} className="flex flex-col gap-1 p-4">
              <span className="flex flex-wrap items-center gap-2">
                {canWrite ? (
                  <Link
                    href={`/report-templates/${t.id}`}
                    className="font-medium text-primary hover:underline"
                  >
                    {t.name}
                  </Link>
                ) : (
                  <span className="font-medium">{t.name}</span>
                )}
                <span className="text-sm text-muted-foreground">v{t.version}</span>
                {!t.is_active && <Badge variant="outline">Inactive</Badge>}
              </span>
              {t.description && (
                <span className="text-sm text-muted-foreground">{t.description}</span>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function DownloadButton({
  locationId,
  template,
  pestpacLocationId,
}: {
  locationId: string;
  template: ReportTemplateRead;
  pestpacLocationId: number;
}) {
  const [state, setState] = useState<{ pending: boolean; error?: unknown }>({ pending: false });
  const download = async () => {
    setState({ pending: true });
    try {
      const blob = await fetchPdf(getReportsGenerateReportUrl(locationId, template.id));
      saveBlob(blob, `${template.name} - ${pestpacLocationId}.pdf`);
      setState({ pending: false });
    } catch (error) {
      setState({ pending: false, error });
    }
  };
  return (
    <li className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="outline" size="sm" disabled={state.pending} onClick={download}>
          <FileDown aria-hidden />
          {state.pending ? "Generating…" : template.name}
        </Button>
        {template.description && (
          <span className="text-sm text-muted-foreground">{template.description}</span>
        )}
      </div>
      {state.error !== undefined && (
        <p className="text-sm text-destructive">
          {errorMessage(state.error, "Could not generate the report.")}
        </p>
      )}
    </li>
  );
}

/** PDF downloads for a location, one per active template of its company. */
export function LocationReports({
  companyId,
  locationId,
  pestpacLocationId,
}: {
  companyId: string;
  locationId: string;
  pestpacLocationId: number;
}) {
  const templates = useReportsListReportTemplates(companyId);
  if (templates.isPending) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (templates.isError) {
    return (
      <p className="text-sm text-destructive">
        {errorMessage(templates.error, "Could not load reports.")}
      </p>
    );
  }
  if (templates.data.data.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">No reports are set up for this customer.</p>
    );
  }
  return (
    <ul className="flex flex-col gap-3">
      {templates.data.data.map((t) => (
        <DownloadButton
          key={t.id}
          locationId={locationId}
          template={t}
          pestpacLocationId={pestpacLocationId}
        />
      ))}
    </ul>
  );
}
