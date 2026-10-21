// Orval mutator: every generated call goes through the Next.js BFF, never to FastAPI directly.
import { CSRF_HEADER, readCsrfToken } from "@/lib/csrf";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: unknown,
  ) {
    super(`Request failed with status ${status}`);
  }
}

export const bffFetch = async <T>(url: string, options: RequestInit = {}): Promise<T> => {
  const method = (options.method ?? "GET").toUpperCase();
  const headers = new Headers(options.headers);
  if (method !== "GET" && method !== "HEAD") {
    const csrf = readCsrfToken();
    if (csrf) headers.set(CSRF_HEADER, csrf);
  }

  const res = await fetch(`/api/bff${url}`, { ...options, headers, credentials: "same-origin" });
  const text = await res.text();
  const data: unknown = text ? JSON.parse(text) : undefined;

  if (!res.ok) throw new ApiError(res.status, data);
  return { data, status: res.status, headers: res.headers } as T;
};
