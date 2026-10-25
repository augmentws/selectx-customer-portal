"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, FileDown, Plus, RefreshCw, Sparkles, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { formatPestPacDate } from "@/components/service-order-list";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { useDocumentTitle } from "@/lib/use-document-title";
import { errorMessage } from "@/lib/api/errors";
import type { ReportPhotoItem, ReportRead, TemplateField } from "@/lib/api/generated/model";
import {
  getReportsGetServiceReportPdfUrl,
  getReportsGetServiceReportQueryKey,
  getReportsPreviewServiceReportUrl,
  useReportsDraftServiceReport,
  useReportsFinalizeServiceReport,
  useReportsGetServiceReport,
  useReportsReviseServiceReport,
  useReportsUpdateServiceReport,
} from "@/lib/api/generated/reports/reports";
import { fetchHtml } from "@/lib/api/pdf";
import { usePermissions } from "@/lib/permissions";
import { useUrlTab } from "@/lib/use-url-tab";

const POLL_MS = 3000;

// A "sections" field value (field values are free-form JSON in the API contract).
type ReportSection = { heading: string; paragraphs: string[] };
type FieldValue = string | string[] | ReportSection[];
type Fields = Record<string, FieldValue>;

// Paragraphs are edited as text with blank lines between them; list items one per line.
const toParagraphText = (v: unknown) => (Array.isArray(v) ? v.join("\n\n") : "");
const fromParagraphText = (t: string) =>
  t
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean);
const toLines = (v: unknown) => (Array.isArray(v) ? v.join("\n") : "");
const fromLines = (t: string) =>
  t
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

const STATUS_LABEL: Record<string, string> = {
  draft: "Draft",
  drafting: "Drafting narrative…",
  final: "Final",
  superseded: "Superseded",
};

function move<T>(list: T[], from: number, to: number): T[] {
  if (to < 0 || to >= list.length) return list;
  const next = [...list];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

function FieldEditor({
  field,
  value,
  disabled,
  onChange,
}: {
  field: TemplateField;
  value: unknown;
  disabled: boolean;
  onChange: (v: FieldValue) => void;
}) {
  const id = `field-${field.key}`;
  const help = field.help ? `${id}-help` : undefined;
  const label = (
    <Label htmlFor={field.type === "sections" ? undefined : id}>
      {field.label}
      {field.llm && (
        <Badge variant="outline" className="ml-2">
          Drafted
        </Badge>
      )}
    </Label>
  );
  const helpText = field.help && (
    <p id={help} className="text-sm text-muted-foreground">
      {field.help}
    </p>
  );
  if (field.type === "text") {
    return (
      <div className="flex flex-col gap-2">
        {label}
        <Input
          id={id}
          aria-describedby={help}
          disabled={disabled}
          value={typeof value === "string" ? value : ""}
          onChange={(e) => onChange(e.target.value)}
        />
        {helpText}
      </div>
    );
  }
  if (field.type === "paragraphs" || field.type === "list") {
    const paragraphs = field.type === "paragraphs";
    return (
      <div className="flex flex-col gap-2">
        {label}
        <Textarea
          id={id}
          aria-describedby={help}
          disabled={disabled}
          className="min-h-32"
          defaultValue={paragraphs ? toParagraphText(value) : toLines(value)}
          onChange={(e) =>
            onChange(paragraphs ? fromParagraphText(e.target.value) : fromLines(e.target.value))
          }
        />
        <p className="text-xs text-muted-foreground">
          {paragraphs ? "A blank line starts a new paragraph." : "One item per line."} Use **double
          asterisks** for bold.
        </p>
        {helpText}
      </div>
    );
  }
  const sections = (Array.isArray(value) ? value : []) as ReportSection[];
  const set = (next: ReportSection[]) => onChange(next);
  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="mb-2">{label}</legend>
      {helpText}
      {sections.map((section, n) => (
        <div key={n} className="flex flex-col gap-2 border border-border bg-card p-3">
          <div className="flex items-center gap-2">
            <Input
              aria-label={`Section ${n + 1} heading`}
              disabled={disabled}
              value={section.heading}
              onChange={(e) =>
                set(sections.map((s, i) => (i === n ? { ...s, heading: e.target.value } : s)))
              }
            />
            <Button
              variant="ghost"
              size="icon"
              disabled={disabled || n === 0}
              aria-label="Move section up"
              onClick={() => set(move(sections, n, n - 1))}
            >
              <ArrowUp aria-hidden />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              disabled={disabled || n === sections.length - 1}
              aria-label="Move section down"
              onClick={() => set(move(sections, n, n + 1))}
            >
              <ArrowDown aria-hidden />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              disabled={disabled}
              aria-label="Remove section"
              onClick={() => set(sections.filter((_, i) => i !== n))}
            >
              <Trash2 aria-hidden />
            </Button>
          </div>
          <Textarea
            aria-label={`Section ${n + 1} text`}
            disabled={disabled}
            className="min-h-24"
            defaultValue={toParagraphText(section.paragraphs)}
            onChange={(e) =>
              set(
                sections.map((s, i) =>
                  i === n ? { ...s, paragraphs: fromParagraphText(e.target.value) } : s,
                ),
              )
            }
          />
        </div>
      ))}
      <div>
        <Button
          variant="outline"
          size="sm"
          disabled={disabled}
          onClick={() => set([...sections, { heading: "", paragraphs: [] }])}
        >
          <Plus aria-hidden />
          Add section
        </Button>
      </div>
    </fieldset>
  );
}

function PhotoRow({
  photo,
  index,
  count,
  disabled,
  onChange,
  onMove,
}: {
  photo: ReportPhotoItem;
  index: number;
  count: number;
  disabled: boolean;
  onChange: (p: ReportPhotoItem) => void;
  onMove: (to: number) => void;
}) {
  return (
    <li className="flex flex-wrap items-start gap-3 p-3">
      {/* Thumbnails come through the BFF; lazy, since originals are full-size. */}
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={`/api/bff/v1/documents/${photo.document_id}/file`}
        alt={photo.name ?? ""}
        loading="lazy"
        className="h-24 w-32 rounded border border-border object-cover"
      />
      <div className="flex min-w-48 flex-1 flex-col gap-2">
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            className="size-4 accent-primary"
            disabled={disabled}
            checked={photo.selected}
            onChange={(e) => onChange({ ...photo, selected: e.target.checked })}
          />
          Include · {formatPestPacDate(photo.document_date, true)} · DocumentID{" "}
          {photo.pestpac_document_id}
        </label>
        <Input
          aria-label="Caption"
          placeholder="Caption"
          disabled={disabled}
          value={photo.caption ?? ""}
          onChange={(e) => onChange({ ...photo, caption: e.target.value || null })}
        />
      </div>
      <div className="flex gap-1">
        <Button
          variant="ghost"
          size="icon"
          disabled={disabled || index === 0}
          aria-label="Move photo up"
          onClick={() => onMove(index - 1)}
        >
          <ArrowUp aria-hidden />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          disabled={disabled || index === count - 1}
          aria-label="Move photo down"
          onClick={() => onMove(index + 1)}
        >
          <ArrowDown aria-hidden />
        </Button>
      </div>
    </li>
  );
}

function Preview({ reportId, version }: { reportId: string; version: string }) {
  const [state, setState] = useState<{ html?: string; error?: unknown; pending: boolean }>({
    pending: false,
  });
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const load = async () => {
    setState({ pending: true });
    try {
      setState({
        html: await fetchHtml(getReportsPreviewServiceReportUrl(reportId)),
        pending: false,
      });
    } catch (error) {
      setState({ error, pending: false });
    }
    setLoadedFor(version);
  };
  const stale = loadedFor !== null && loadedFor !== version;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="outline" disabled={state.pending} onClick={load}>
          <RefreshCw aria-hidden />
          {state.pending ? "Rendering…" : loadedFor ? "Refresh preview" : "Show preview"}
        </Button>
        <span className="text-sm text-muted-foreground">
          {stale
            ? "The saved report changed since this preview; refresh it."
            : "Rendered from the saved report, exactly as the PDF will be. Save edits first."}
        </span>
      </div>
      {state.error !== undefined && (
        <Alert variant="destructive">
          <AlertDescription>{errorMessage(state.error, "Preview failed.")}</AlertDescription>
        </Alert>
      )}
      {state.html && (
        // sandbox="": no scripts, no same-origin access; it's only shown.
        <iframe
          title="Report preview"
          sandbox=""
          srcDoc={state.html}
          className="h-[80vh] w-full border border-border bg-white"
        />
      )}
    </div>
  );
}

function Editor({ report }: { report: ReportRead }) {
  const router = useRouter();
  const [tab, setTab] = useUrlTab(
    ["sources", "report", "preview"],
    report.drafted_at ? "report" : "sources",
  );
  const queryClient = useQueryClient();
  const { can } = usePermissions();
  const canWrite = can("reports:write", report.operator_id);
  const locked = report.status !== "draft" || !canWrite;

  // Local edits; the component is keyed by updated_at, so a saved report resets them.
  const [fields, setFields] = useState<Fields>(report.data.fields as Fields);
  const [notes, setNotes] = useState(report.data.notes);
  const techComment = report.data.technician_comment ?? null;
  const [useComment, setUseComment] = useState(techComment?.selected ?? false);
  const [photos, setPhotos] = useState(report.data.photos);
  const [dirty, setDirty] = useState(false);
  const edit =
    <T,>(set: (v: T) => void) =>
    (v: T) => {
      set(v);
      setDirty(true);
    };

  const key = getReportsGetServiceReportQueryKey(report.id);
  const onSaved = (res: { data: ReportRead }) => queryClient.setQueryData(key, res);
  const update = useReportsUpdateServiceReport({ mutation: { onSuccess: onSaved } });
  const draft = useReportsDraftServiceReport({ mutation: { onSuccess: onSaved } });
  const finalize = useReportsFinalizeServiceReport({ mutation: { onSuccess: onSaved } });
  const revise = useReportsReviseServiceReport({
    mutation: { onSuccess: (res) => router.push(`/service-reports/${res.data.id}`) },
  });
  const busy = update.isPending || draft.isPending || finalize.isPending;

  const changes = () => ({
    fields,
    notes: notes.map((n) => ({ note_id: n.note_id, selected: n.selected })),
    ...(techComment ? { technician_comment_selected: useComment } : {}),
    photos: photos.map((p) => ({
      document_id: p.document_id,
      selected: p.selected,
      caption: p.caption,
    })),
  });
  const save = () => update.mutateAsync({ reportId: report.id, data: changes() });
  const saveThen = async (next: () => Promise<unknown>) => {
    if (dirty) await save();
    await next();
  };

  const selectedNotes = notes.filter((n) => n.selected).length;
  const commentSelected = techComment !== null && useComment;
  // What the narrative is drafted from: selected notes, plus the technician comment.
  const sources = [
    selectedNotes > 0 ? `${selectedNotes} note${selectedNotes === 1 ? "" : "s"}` : "",
    commentSelected ? "the technician comment" : "",
  ]
    .filter(Boolean)
    .join(" and ");
  const error = update.error ?? draft.error ?? finalize.error ?? revise.error;

  return (
    <div className="flex flex-col gap-4">
      {report.status === "drafting" && (
        <Alert>
          <AlertDescription>
            Drafting the narrative from {sources}… This page updates when it&apos;s done.
          </AlertDescription>
        </Alert>
      )}
      {report.draft_error && (
        <Alert variant="destructive">
          <AlertDescription>Drafting failed: {report.draft_error}</AlertDescription>
        </Alert>
      )}
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{errorMessage(error)}</AlertDescription>
        </Alert>
      )}

      {report.latest_id !== report.id && (
        <Alert>
          <AlertDescription>
            {report.status === "superseded"
              ? "A newer version of this report replaced this one; only the newest version is final."
              : "A newer version of this report exists."}{" "}
            <Link href={`/service-reports/${report.latest_id}`} className="text-primary underline">
              Open the latest version
            </Link>
          </AlertDescription>
        </Alert>
      )}

      {(report.has_pdf || (canWrite && report.status !== "superseded")) && (
        <div className="flex flex-wrap items-center gap-3">
          {report.has_pdf && (
            <a
              href={`/api/bff${getReportsGetServiceReportPdfUrl(report.id)}`}
              target="_blank"
              rel="noopener"
              className={buttonVariants({ variant: "outline" })}
            >
              <FileDown aria-hidden />
              Open PDF
            </a>
          )}
          {!canWrite || report.status === "superseded" ? null : report.status === "final" ? (
            <Button
              variant="outline"
              disabled={revise.isPending || report.latest_id !== report.id}
              onClick={() => revise.mutate({ reportId: report.id })}
            >
              {revise.isPending ? "Starting…" : `New version (revision ${report.revision + 1})`}
            </Button>
          ) : (
            <>
              <Button disabled={locked || busy || !dirty} onClick={() => save()}>
                {update.isPending ? "Saving…" : dirty ? "Save changes" : "Saved"}
              </Button>
              <Button
                variant="outline"
                disabled={locked || busy || (selectedNotes === 0 && !commentSelected)}
                onClick={() => saveThen(() => draft.mutateAsync({ reportId: report.id }))}
              >
                <Sparkles aria-hidden />
                {report.drafted_at ? "Re-draft narrative" : "Draft narrative"}
              </Button>
              <Button
                variant="outline"
                disabled={locked || busy}
                onClick={() => saveThen(() => finalize.mutateAsync({ reportId: report.id }))}
              >
                <FileDown aria-hidden />
                {finalize.isPending ? "Generating…" : "Generate PDF"}
              </Button>
              <span className="text-sm text-muted-foreground">
                Generating the PDF stores it and locks this revision.
              </span>
            </>
          )}
        </div>
      )}

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="sources">Notes and photos</TabsTrigger>
          <TabsTrigger value="report">Report</TabsTrigger>
          <TabsTrigger value="preview">Preview</TabsTrigger>
        </TabsList>

        <TabsContent value="sources" className="flex flex-col gap-6 pt-4">
          {techComment && (
            <section className="flex flex-col gap-2">
              <h2 className="text-xl">Technician comment</h2>
              <p className="text-sm text-muted-foreground">
                The comment on the service order in PestPac, as it was when the report was started.
                Sent with the selected notes when checked.
              </p>
              <div className="flex gap-3 border border-border bg-card p-3">
                <input
                  type="checkbox"
                  className="mt-1 size-4 accent-primary"
                  aria-label="Use the technician comment"
                  disabled={locked}
                  checked={useComment}
                  onChange={(e) => edit(setUseComment)(e.target.checked)}
                />
                <div className="flex flex-col gap-1">
                  {techComment.author && (
                    <span className="text-sm text-muted-foreground">{techComment.author}</span>
                  )}
                  <p className="text-sm whitespace-pre-line">{techComment.text}</p>
                </div>
              </div>
            </section>
          )}
          <section className="flex flex-col gap-2">
            <h2 className="text-xl">Notes ({selectedNotes} selected)</h2>
            <p className="text-sm text-muted-foreground">
              Notes from the day before to the day after the work date. Those on the work date, or
              linked to the order, start selected. Selected notes (and the technician comment, when
              checked) are what the narrative is drafted from.
            </p>
            <ul className="divide-y divide-border border border-border bg-card">
              {notes.length === 0 && (
                <li className="p-4 text-muted-foreground">
                  No notes near the work date. Sync the location&apos;s service orders to collect
                  notes.
                </li>
              )}
              {notes.map((n, i) => (
                <li key={n.note_id} className="flex gap-3 p-3">
                  <input
                    type="checkbox"
                    className="mt-1 size-4 accent-primary"
                    aria-label={`Use note ${n.pestpac_note_id}`}
                    disabled={locked}
                    checked={n.selected}
                    onChange={(e) =>
                      edit(setNotes)(
                        notes.map((x, j) => (j === i ? { ...x, selected: e.target.checked } : x)),
                      )
                    }
                  />
                  <div className="flex flex-col gap-1">
                    <span className="text-sm text-muted-foreground">
                      {formatPestPacDate(n.note_date, true)}
                      {n.author && ` · ${n.author}`}
                      {n.note_code && ` · ${n.note_code}`}
                      {n.linked_to_order && " · linked to this order"}
                    </span>
                    <p className="text-sm whitespace-pre-line">{n.text}</p>
                  </div>
                </li>
              ))}
            </ul>
          </section>
          <section className="flex flex-col gap-2">
            <h2 className="text-xl">Photos ({photos.filter((p) => p.selected).length} selected)</h2>
            <p className="text-sm text-muted-foreground">
              Images from the day before to the day after the work date. Selected photos appear in
              the report in this order, with their captions.
            </p>
            <ul className="divide-y divide-border border border-border bg-card">
              {photos.length === 0 && (
                <li className="p-4 text-muted-foreground">
                  No photos near the work date. Sync location to collect them.
                </li>
              )}
              {photos.map((p, i) => (
                <PhotoRow
                  key={p.document_id}
                  photo={p}
                  index={i}
                  count={photos.length}
                  disabled={locked}
                  onChange={(next) => edit(setPhotos)(photos.map((x, j) => (j === i ? next : x)))}
                  onMove={(to) => edit(setPhotos)(move(photos, i, to))}
                />
              ))}
            </ul>
          </section>
        </TabsContent>

        <TabsContent value="report" className="flex flex-col gap-5 pt-4">
          {!report.drafted_at && (
            <p className="text-sm text-muted-foreground">
              Fields marked Drafted are filled by Draft narrative from the selected notes. You can
              also write them yourself.
            </p>
          )}
          {report.template_fields.map((f) => (
            <FieldEditor
              key={f.key}
              field={f}
              value={fields[f.key]}
              disabled={locked}
              onChange={(v) => edit(setFields)({ ...fields, [f.key]: v })}
            />
          ))}
        </TabsContent>

        <TabsContent value="preview" className="pt-4">
          <Preview reportId={report.id} version={report.updated_at} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export function ServiceReportEditor() {
  const { reportId } = useParams<{ reportId: string }>();
  const report = useReportsGetServiceReport(reportId, {
    query: {
      refetchInterval: (q) => (q.state.data?.data.status === "drafting" ? POLL_MS : false),
    },
  });
  useDocumentTitle(
    report.data &&
      `Report ${report.data.data.revision > 1 ? `r${report.data.data.revision}` : ""}`.trim(),
    report.data?.data.trail.find((c) => c.kind === "location")?.name,
  );
  if (report.isPending) return <p className="text-muted-foreground">Loading…</p>;
  if (report.isError) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{errorMessage(report.error, "Report not found.")}</AlertDescription>
      </Alert>
    );
  }
  const r = report.data.data;
  const order = r.data.context.service_order as
    | { order_number?: string | null; pestpac_order_id?: number; work_date?: string | null }
    | undefined;
  return (
    <div className="flex flex-col gap-6">
      <div>
        <Breadcrumbs trail={r.trail} />
        <h1 className="mt-2 flex flex-wrap items-center gap-3 text-3xl">
          {r.template_name}
          <Badge variant={r.status === "final" ? "success" : "secondary"}>
            {STATUS_LABEL[r.status] ?? r.status}
          </Badge>
          {r.revision > 1 && <Badge variant="outline">Revision {r.revision}</Badge>}
        </h1>
        <p className="text-muted-foreground">
          Order {order?.order_number ?? order?.pestpac_order_id}
          {order?.work_date && ` · worked ${formatPestPacDate(order.work_date, true)}`}
        </p>
      </div>
      <Editor key={r.updated_at} report={r} />
    </div>
  );
}
