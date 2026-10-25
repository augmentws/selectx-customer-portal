"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Breadcrumbs } from "@/components/breadcrumbs";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { NativeSelect, NativeSelectOption } from "@/components/ui/native-select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/page-tabs";
import { Textarea } from "@/components/ui/textarea";
import { useDocumentTitle } from "@/lib/use-document-title";
import { errorMessage } from "@/lib/api/errors";
import { useCompaniesGetCompany } from "@/lib/api/generated/companies/companies";
import { useBillTosListLocations } from "@/lib/api/generated/bill-tos/bill-tos";
import { useCompaniesListBillTos } from "@/lib/api/generated/companies/companies";
import type { ReportTemplateRead, TemplateField } from "@/lib/api/generated/model";
import {
  getReportsGetReportTemplateQueryKey,
  getReportsListReportTemplatesQueryKey,
  getReportsPreviewReportUrl,
  useReportsCreateReportTemplate,
  useReportsGetReportTemplate,
  useReportsUpdateReportTemplate,
} from "@/lib/api/generated/reports/reports";
import { fetchPdf } from "@/lib/api/pdf";
import { useUrlTab } from "@/lib/use-url-tab";

const STARTER_HTML = `<!doctype html>
<html>
<head>
<style>
  @page { size: letter; margin: 0.75in; @bottom-right { content: "Page " counter(page) " of " counter(pages); font-size: 9pt; } }
  body { font-family: sans-serif; font-size: 11pt; }
  h1 { font-size: 18pt; margin: 0 0 4pt; }
</style>
</head>
<body>
  <h1>{{ company.name }}</h1>
  <p>{{ location.name }}<br>
     {{ location.address }}{% if location.address2 %}, {{ location.address2 }}{% endif %}<br>
     {{ location.city }}, {{ location.state }} {{ location.zip }}</p>
  <p>Prepared by {{ operator.name }} on {{ generated_at.strftime('%B %d, %Y') }}</p>
</body>
</html>
`;

/** The fields JSON must parse to an array; the API checks each field's shape. */
const fieldsJson = z.string().refine((text) => {
  try {
    return Array.isArray(JSON.parse(text || "[]"));
  } catch {
    return false;
  }
}, "Must be a JSON array of fields");

const schema = z.object({
  name: z.string().trim().min(1, "Required").max(200),
  description: z.string().max(1000),
  html: z.string().min(1, "Required"),
  fields: fieldsJson,
  prompt: z.string().max(50_000),
  llm_model: z.string().max(200),
  is_active: z.boolean(),
});

const parseFields = (text: string): TemplateField[] => JSON.parse(text || "[]");
type FormValues = z.infer<typeof schema>;

const VARIABLES = [
  ["operator", "name"],
  ["company", "name"],
  [
    "bill_to",
    "pestpac_bill_to_id, name, description, pestpac_bill_to_code, pestpac_company, address, address2, city, state, zip, phone",
  ],
  [
    "location",
    "pestpac_location_id, pestpac_location_code, name, address, address2, city, state, zip, phone, email, pestpac_type, account_type, latitude, longitude",
  ],
  ["generated_at", "a UTC datetime, e.g. generated_at.strftime('%B %d, %Y')"],
  ["store_number", "parsed from the location name, or None"],
  [
    "service_order",
    "service reports only (else None): pestpac_order_id, order_number, work_date, service_code, description, technician_name, service_number",
  ],
  [
    "conditions",
    "open conditions: pestpac_issue_id, area, area_hierarchy, condition, category, severity, responsibility, status, date_opened, action",
  ],
  ["fields", "the fields below, by key; render text with |rich for **bold**"],
  ["photos", "selected photos: src (embedded), caption"],
] as const;

function VariablesHelp() {
  return (
    <details className="text-sm">
      <summary className="cursor-pointer text-primary hover:underline">Available variables</summary>
      <dl className="mt-2 flex flex-col gap-1">
        {VARIABLES.map(([name, fields]) => (
          <div key={name}>
            <dt className="inline font-mono font-medium">{name}</dt>
            <dd className="inline text-muted-foreground">: {fields}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-2 text-muted-foreground">
        Jinja syntax. An unknown variable is an error. Images and fonts must be embedded as{" "}
        <code>data:</code> URIs; external URLs are not loaded.
      </p>
    </details>
  );
}

/** Renders the form's current (unsaved) HTML against a chosen location. */
function PreviewPanel({
  companyId,
  getHtml,
  getFields,
}: {
  companyId: string;
  getHtml: () => string;
  getFields: () => TemplateField[] | null;
}) {
  const billTos = useCompaniesListBillTos(companyId);
  const [billToId, setBillToId] = useState("");
  const locations = useBillTosListLocations(billToId, { query: { enabled: billToId !== "" } });
  const [locationId, setLocationId] = useState("");
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [state, setState] = useState<{ pending: boolean; error?: unknown }>({ pending: false });

  useEffect(() => {
    return () => {
      if (pdfUrl) URL.revokeObjectURL(pdfUrl);
    };
  }, [pdfUrl]);

  const preview = async () => {
    setState({ pending: true });
    try {
      const blob = await fetchPdf(getReportsPreviewReportUrl(locationId), {
        method: "POST",
        json: { html: getHtml(), fields: getFields() ?? [] },
      });
      setPdfUrl(URL.createObjectURL(blob));
      setState({ pending: false });
    } catch (error) {
      setState({ pending: false, error });
    }
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Preview</CardTitle>
        <CardDescription>
          Renders the HTML above, saved or not, with a real location. Fields, the service order,
          conditions, and photos use sample values.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-2">
            <Label htmlFor="preview-bill-to">Bill-to</Label>
            <NativeSelect
              id="preview-bill-to"
              value={billToId}
              onChange={(e) => {
                setBillToId(e.target.value);
                setLocationId("");
              }}
            >
              <NativeSelectOption value="">Choose a bill-to</NativeSelectOption>
              {billTos.data?.data.map((b) => (
                <NativeSelectOption key={b.id} value={b.id}>
                  {b.name}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="preview-location">Location</Label>
            <NativeSelect
              id="preview-location"
              value={locationId}
              disabled={!locations.data}
              onChange={(e) => setLocationId(e.target.value)}
            >
              <NativeSelectOption value="">Choose a location</NativeSelectOption>
              {locations.data?.data.map((l) => (
                <NativeSelectOption key={l.id} value={l.id}>
                  {l.pestpac_company ?? `LocationID ${l.pestpac_location_id}`}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          </div>
          <Button variant="outline" disabled={!locationId || state.pending} onClick={preview}>
            {state.pending ? "Rendering…" : "Preview PDF"}
          </Button>
        </div>
        {billTos.data?.data.length === 0 && (
          <p className="text-sm text-muted-foreground">
            Onboard a bill-to for this company to preview with real data.
          </p>
        )}
        {state.error !== undefined && (
          <Alert variant="destructive">
            <AlertDescription>{errorMessage(state.error, "Preview failed.")}</AlertDescription>
          </Alert>
        )}
        {pdfUrl && (
          <iframe
            src={pdfUrl}
            title="Report preview"
            className="h-[80vh] w-full rounded-lg border border-border"
          />
        )}
      </CardContent>
    </Card>
  );
}

/** Marks a tab whose panel has a validation error. */
function TabError() {
  return (
    <span className="ml-1 text-destructive" aria-label="has an error">
      •
    </span>
  );
}

function EditorForm({ companyId, template }: { companyId: string; template?: ReportTemplateRead }) {
  const [tab, setTab] = useUrlTab(["template", "data", "prompt"], "template");
  const router = useRouter();
  const queryClient = useQueryClient();
  const listKey = getReportsListReportTemplatesQueryKey(companyId);
  const create = useReportsCreateReportTemplate({
    mutation: {
      onSuccess: (res) => {
        queryClient.invalidateQueries({ queryKey: listKey });
        router.replace(`/report-templates/${res.data.id}`);
      },
    },
  });
  const update = useReportsUpdateReportTemplate({
    mutation: {
      onSuccess: (res) => {
        queryClient.setQueryData(getReportsGetReportTemplateQueryKey(res.data.id), res);
        queryClient.invalidateQueries({ queryKey: listKey });
      },
    },
  });
  const save = template ? update : create;
  const {
    register,
    handleSubmit,
    getValues,
    formState: { errors, isDirty },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    values: {
      name: template?.name ?? "",
      description: template?.description ?? "",
      html: template?.html ?? STARTER_HTML,
      fields: JSON.stringify(template?.fields ?? [], null, 2),
      prompt: template?.prompt ?? "",
      llm_model: template?.llm_model ?? "",
      is_active: template?.is_active ?? true,
    },
  });

  const onSubmit = (values: FormValues) => {
    const data = {
      name: values.name,
      description: values.description || null,
      html: values.html,
      fields: parseFields(values.fields),
      prompt: values.prompt || null,
      llm_model: values.llm_model.trim() || null,
    };
    if (template) {
      update.mutate({ templateId: template.id, data: { ...data, is_active: values.is_active } });
    } else {
      create.mutate({ companyId, data });
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-4" noValidate>
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="flex flex-col gap-2">
            <Label htmlFor="rt-name">Name</Label>
            <Input id="rt-name" {...register("name")} />
            {errors.name && <p className="text-sm text-destructive">{errors.name.message}</p>}
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="rt-description">Description</Label>
            <Input id="rt-description" {...register("description")} />
          </div>
        </div>
        {/* Panels stay mounted so the form keeps every field registered and validated. */}
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="template">Template{errors.html && <TabError />}</TabsTrigger>
            <TabsTrigger value="data">Data{errors.fields && <TabError />}</TabsTrigger>
            <TabsTrigger value="prompt">Prompt</TabsTrigger>
          </TabsList>
          <TabsContent value="template" keepMounted className="flex flex-col gap-2 pt-4">
            <Label htmlFor="rt-html">HTML template</Label>
            <Textarea
              id="rt-html"
              spellCheck={false}
              className="min-h-96 font-mono text-sm md:text-xs"
              {...register("html")}
            />
            {errors.html && <p className="text-sm text-destructive">{errors.html.message}</p>}
            <VariablesHelp />
          </TabsContent>
          <TabsContent value="data" keepMounted className="flex flex-col gap-2 pt-4">
            <Label htmlFor="rt-fields">Report fields (JSON)</Label>
            <Textarea
              id="rt-fields"
              spellCheck={false}
              className="min-h-48 font-mono text-sm md:text-xs"
              aria-describedby="rt-fields-help"
              {...register("fields")}
            />
            <p id="rt-fields-help" className="text-sm text-muted-foreground">
              What a service report from this template edits. Each field: <code>key</code>,{" "}
              <code>label</code>, <code>type</code> (text, paragraphs, list, sections), optional{" "}
              <code>llm</code> (drafted from the order&apos;s notes), <code>help</code>, and{" "}
              <code>default</code>.
            </p>
            {errors.fields && <p className="text-sm text-destructive">{errors.fields.message}</p>}
          </TabsContent>
          <TabsContent value="prompt" keepMounted className="flex flex-col gap-4 pt-4">
            <div className="flex flex-col gap-2">
              <Label htmlFor="rt-prompt">Drafting prompt</Label>
              <Textarea
                id="rt-prompt"
                className="min-h-48 font-mono text-sm md:text-xs"
                aria-describedby="rt-prompt-help"
                {...register("prompt")}
              />
              <p id="rt-prompt-help" className="text-sm text-muted-foreground">
                Instructions for drafting the <code>llm</code> fields from the selected notes. Each
                field&apos;s label and help are added automatically, so the prompt and fields stay
                in step.
              </p>
            </div>
            <div className="flex max-w-md flex-col gap-2">
              <Label htmlFor="rt-model">Model (optional)</Label>
              <Input
                id="rt-model"
                placeholder="OpenRouter model id; blank uses the default"
                {...register("llm_model")}
              />
            </div>
          </TabsContent>
        </Tabs>
        {template && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="size-4 accent-primary" {...register("is_active")} />
            Active (available for download on this company&apos;s locations)
          </label>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={save.isPending || (template && !isDirty)}>
            {save.isPending ? "Saving…" : template ? "Save changes" : "Create template"}
          </Button>
          {template && (
            <span className="text-sm text-muted-foreground">
              Version {template.version} · updated {new Date(template.updated_at).toLocaleString()}
            </span>
          )}
        </div>
        {save.isError && (
          <Alert variant="destructive">
            <AlertDescription>{errorMessage(save.error)}</AlertDescription>
          </Alert>
        )}
        {update.isSuccess && !isDirty && (
          <p className="text-sm text-success" role="status">
            Saved.
          </p>
        )}
      </form>
      <PreviewPanel
        companyId={companyId}
        getHtml={() => getValues("html")}
        getFields={() => {
          try {
            return parseFields(getValues("fields"));
          } catch {
            return null; // invalid JSON: preview without fields; saving reports the error
          }
        }}
      />
    </div>
  );
}

/** Breadcrumbs for pages beneath a company: its operator, then the company itself. */
function CompanyCrumbs({ companyId }: { companyId: string }) {
  const company = useCompaniesGetCompany(companyId);
  const c = company.data?.data;
  return c ? (
    <Breadcrumbs trail={[...c.trail, { kind: "company", id: c.id, name: c.name }]} />
  ) : null;
}

export function NewReportTemplate() {
  const { companyId } = useParams<{ companyId: string }>();
  useDocumentTitle("New report template");
  return (
    <div className="flex flex-col gap-6">
      <div>
        <CompanyCrumbs companyId={companyId} />
        <h1 className="mt-2 text-3xl">New report template</h1>
      </div>
      <EditorForm companyId={companyId} />
    </div>
  );
}

export function EditReportTemplate() {
  const { templateId } = useParams<{ templateId: string }>();
  const template = useReportsGetReportTemplate(templateId);
  useDocumentTitle(template.data?.data.name, "Report template");
  if (template.isPending) return <p className="text-muted-foreground">Loading…</p>;
  if (template.isError) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{errorMessage(template.error, "Template not found.")}</AlertDescription>
      </Alert>
    );
  }
  const t = template.data.data;
  return (
    <div className="flex flex-col gap-6">
      <div>
        <CompanyCrumbs companyId={t.company_id} />
        <h1 className="mt-2 text-3xl">{t.name}</h1>
      </div>
      <EditorForm companyId={t.company_id} template={t} />
    </div>
  );
}
