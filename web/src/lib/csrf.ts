// Shared between browser and server: the CSRF cookie is deliberately readable by JS
// (double-submit pattern). It carries no authority on its own.
export const CSRF_COOKIE = "cp_csrf";
export const CSRF_HEADER = "x-csrf-token";

export function readCsrfToken(): string | undefined {
  if (typeof document === "undefined") return undefined;
  const raw = document.cookie
    .split("; ")
    .find((c) => c.startsWith(`${CSRF_COOKIE}=`))
    ?.slice(CSRF_COOKIE.length + 1);
  return raw ? decodeURIComponent(raw) : undefined;
}
