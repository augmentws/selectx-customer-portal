"use client";

import { FileText, Image as ImageIcon } from "lucide-react";
import { useState } from "react";

import { formatPestPacDate } from "@/components/service-order-list";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { errorMessage } from "@/lib/api/errors";
import { useLocationsListDocuments } from "@/lib/api/generated/locations/locations";
import type { DocumentRead } from "@/lib/api/generated/model";
import { useUrlTab } from "@/lib/use-url-tab";

// Through the BFF, so the session cookie authorizes it; the API serves images and PDFs inline.
const fileUrl = (doc: DocumentRead) => `/api/bff/v1/documents/${doc.id}/file`;

const TYPE_LABELS: Record<string, string> = {
  LocationDocument: "Location",
  ConditionDocument: "Condition",
  CallDocument: "Call",
  Form: "Form",
};

function formatSize(bytes: number | null): string {
  if (bytes === null) return "";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** By the stored file's type; before it's stored, by the file name's extension. */
function isImageDocument(doc: DocumentRead): boolean {
  if (doc.content_type) return doc.content_type.startsWith("image/");
  return /\.(jpe?g|png|gif|webp|heic|bmp|tiff?)$/i.test(doc.file_name ?? "");
}

export function DocumentRow({ doc }: { doc: DocumentRead }) {
  const [preview, setPreview] = useState(false);
  const isImage = isImageDocument(doc);
  const Icon = isImage ? ImageIcon : FileText;
  return (
    <li className="p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Icon className="size-4 text-muted-foreground" aria-hidden />
        {doc.has_file ? (
          <a
            href={fileUrl(doc)}
            target="_blank"
            rel="noopener"
            className="font-medium text-primary hover:underline"
          >
            {doc.name ?? doc.file_name ?? `Document ${doc.pestpac_document_id}`}
          </a>
        ) : (
          <span className="font-medium">
            {doc.name ?? doc.file_name ?? `Document ${doc.pestpac_document_id}`}
          </span>
        )}
        <Badge variant="outline">{TYPE_LABELS[doc.document_type] ?? doc.document_type}</Badge>
        {doc.include_on.portal && <Badge variant="secondary">On portal</Badge>}
        <span className="ml-auto text-sm text-muted-foreground">
          {formatPestPacDate(doc.document_date, true)}
        </span>
      </div>
      <div className="mt-1 flex flex-wrap gap-x-4 text-sm text-muted-foreground">
        <span>DocumentID {doc.pestpac_document_id}</span>
        {doc.file_name && <span>{doc.file_name}</span>}
        {doc.has_file && <span>{formatSize(doc.size_bytes)}</span>}
        {!doc.has_file && (
          <span className={doc.file_error ? "text-destructive" : undefined}>
            {doc.file_error ?? "File not stored yet"}
          </span>
        )}
        {doc.has_file && isImage && (
          <button
            type="button"
            className="text-primary hover:underline"
            aria-expanded={preview}
            onClick={() => setPreview((v) => !v)}
          >
            {preview ? "Hide preview" : "Preview"}
          </button>
        )}
      </div>
      {preview && (
        // Loaded only when asked for: the originals are full-size photos.
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={fileUrl(doc)}
          alt={doc.name ?? doc.file_name ?? ""}
          className="mt-3 max-h-96 rounded-lg border border-border"
        />
      )}
    </li>
  );
}

/** The location's PestPac documents. Filled by "Sync location" (they don't sync with orders). */
export function LocationDocuments({ locationId }: { locationId: string }) {
  // Nested in the location page, so it has its own parameter.
  const [tab, setTab] = useUrlTab(["documents", "images"], "documents", "documents");
  const documents = useLocationsListDocuments(locationId);
  const list = documents.data?.data;
  const images = list?.filter(isImageDocument) ?? [];
  const others = list?.filter((d) => !isImageDocument(d)) ?? [];
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-xl">Documents and images{list && ` (${list.length})`}</h2>
      {documents.isPending && <p className="text-muted-foreground">Loading…</p>}
      {documents.isError && (
        <Alert variant="destructive">
          <AlertDescription>
            {errorMessage(documents.error, "Could not load documents.")}
          </AlertDescription>
        </Alert>
      )}
      {list && (
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="documents">Documents ({others.length})</TabsTrigger>
            <TabsTrigger value="images">Images ({images.length})</TabsTrigger>
          </TabsList>
          <TabsContent value="documents" className="pt-2">
            <DocumentList
              docs={others}
              empty="No documents yet. Sync location to fetch them from PestPac."
            />
          </TabsContent>
          <TabsContent value="images" className="pt-2">
            <DocumentList
              docs={images}
              empty="No images yet. Sync location to fetch them from PestPac."
            />
          </TabsContent>
        </Tabs>
      )}
    </section>
  );
}

function DocumentList({ docs, empty }: { docs: DocumentRead[]; empty: string }) {
  return (
    <ul className="divide-y divide-border border border-border bg-card">
      {docs.length === 0 && <li className="p-4 text-muted-foreground">{empty}</li>}
      {docs.map((doc) => (
        <DocumentRow key={doc.id} doc={doc} />
      ))}
    </ul>
  );
}
