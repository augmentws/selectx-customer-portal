// PDF and HTML responses can't go through the generated client: bffFetch parses bodies as JSON.
import { ApiError } from "@/lib/api/fetcher";
import { CSRF_HEADER, readCsrfToken } from "@/lib/csrf";

/** Fetch a PDF from the BFF. Throws ApiError (with the JSON detail) on failure. */
export async function fetchPdf(
  url: string,
  init: { method?: "GET" | "POST"; json?: unknown } = {},
) {
  const method = init.method ?? "GET";
  const headers = new Headers({ accept: "application/pdf" });
  if (method !== "GET") {
    const csrf = readCsrfToken();
    if (csrf) headers.set(CSRF_HEADER, csrf);
  }
  if (init.json !== undefined) headers.set("content-type", "application/json");
  const res = await fetch(`/api/bff${url}`, {
    method,
    headers,
    body: init.json === undefined ? undefined : JSON.stringify(init.json),
    credentials: "same-origin",
  });
  if (!res.ok) {
    const text = await res.text();
    let body: unknown;
    try {
      body = JSON.parse(text);
    } catch {
      body = { detail: text };
    }
    throw new ApiError(res.status, body);
  }
  return res.blob();
}

/** Save a blob as a file via a temporary object URL. */
export function saveBlob(blob: Blob, filename: string) {
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

/** Fetch an HTML document (a report preview) from the BFF as text. Throws ApiError. */
export async function fetchHtml(url: string): Promise<string> {
  const res = await fetch(`/api/bff${url}`, {
    headers: { accept: "text/html" },
    credentials: "same-origin",
  });
  const text = await res.text();
  if (!res.ok) {
    let body: unknown;
    try {
      body = JSON.parse(text);
    } catch {
      body = { detail: text };
    }
    throw new ApiError(res.status, body);
  }
  return text;
}
