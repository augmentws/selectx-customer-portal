import { NextResponse, type NextRequest } from "next/server";

import {
  ACCESS_COOKIE,
  API_URL,
  apiUnreachable,
  REFRESH_COOKIE,
  checkCsrf,
  clearSessionCookies,
  refreshTokens,
  setSessionCookies,
  type TokenPair,
} from "@/lib/server/session";

// Token-issuing endpoints are only reachable through /api/auth/*, which keeps tokens in cookies.
// So of FastAPI's /v1/auth routes, only these pass; matched after dropping trailing slashes, so
// "v1/auth/login/" (FastAPI redirects it to the login route) is refused too.
const ALLOWED_AUTH = new Set(["v1/auth/me", "v1/auth/password"]);

function isBlocked(path: string): boolean {
  const normalized = path.replace(/\/+$/, "");
  return normalized.startsWith("v1/auth/") && !ALLOWED_AUTH.has(normalized);
}

const FORWARDED_REQUEST_HEADERS = ["accept", "content-type"];
const FORWARDED_RESPONSE_HEADERS = [
  "content-type",
  "content-disposition",
  "cache-control",
  "etag",
  // Stored documents are served sandboxed and unsniffed; keep that through the proxy.
  "x-content-type-options",
  "content-security-policy",
];

async function forward(
  req: NextRequest,
  path: string,
  body: ArrayBuffer | undefined,
  access?: string,
) {
  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = req.headers.get(name);
    if (value) headers.set(name, value);
  }
  if (access) headers.set("authorization", `Bearer ${access}`);

  return fetch(`${API_URL}/${path}${req.nextUrl.search}`, {
    method: req.method,
    headers,
    body,
    cache: "no-store",
    // Never follow FastAPI's redirects: one could lead to a route this proxy refuses.
    redirect: "manual",
  });
}

async function handler(req: NextRequest, ctx: RouteContext<"/api/bff/[...path]">) {
  const path = (await ctx.params).path.join("/");
  if (isBlocked(path)) {
    return NextResponse.json({ detail: "Not found" }, { status: 404 });
  }
  if (!checkCsrf(req)) {
    return NextResponse.json({ detail: "CSRF check failed" }, { status: 403 });
  }

  const body = ["GET", "HEAD"].includes(req.method) ? undefined : await req.arrayBuffer();
  let upstream: Response;
  // Access token missing or expired: refresh once, then retry.
  let rotated: TokenPair | null = null;
  const refreshToken = req.cookies.get(REFRESH_COOKIE)?.value;
  try {
    upstream = await forward(req, path, body, req.cookies.get(ACCESS_COOKIE)?.value);
    if (upstream.status === 401 && refreshToken) {
      rotated = await refreshTokens(refreshToken);
      if (rotated) upstream = await forward(req, path, body, rotated.access_token);
    }
  } catch (error) {
    return apiUnreachable(error);
  }

  const headers = new Headers();
  for (const name of FORWARDED_RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  const res = new NextResponse(upstream.body, { status: upstream.status, headers });

  if (rotated) setSessionCookies(req, res, rotated);
  else if (upstream.status === 401 && refreshToken) clearSessionCookies(res);
  return res;
}

export { handler as DELETE, handler as GET, handler as PATCH, handler as POST, handler as PUT };
