import "server-only";

import type { NextRequest, NextResponse } from "next/server";

import { CSRF_COOKIE, CSRF_HEADER } from "@/lib/csrf";

export const ACCESS_COOKIE = "cp_access";
export const REFRESH_COOKIE = "cp_refresh";

export const API_URL = process.env.API_URL ?? "http://127.0.0.1:8001";

const secure = process.env.NODE_ENV === "production";
const REFRESH_MAX_AGE = 60 * 60 * 24 * 14;

export type TokenPair = {
  access_token: string;
  refresh_token: string;
  expires_in: number;
};

export function setSessionCookies(res: NextResponse, tokens: TokenPair) {
  const base = { httpOnly: true, secure, sameSite: "lax" as const, path: "/" };
  res.cookies.set(ACCESS_COOKIE, tokens.access_token, { ...base, maxAge: tokens.expires_in });
  res.cookies.set(REFRESH_COOKIE, tokens.refresh_token, { ...base, maxAge: REFRESH_MAX_AGE });
  res.cookies.set(CSRF_COOKIE, crypto.randomUUID(), {
    httpOnly: false,
    secure,
    sameSite: "lax",
    path: "/",
    maxAge: REFRESH_MAX_AGE,
  });
}

export function clearSessionCookies(res: NextResponse) {
  for (const name of [ACCESS_COOKIE, REFRESH_COOKIE, CSRF_COOKIE]) res.cookies.delete(name);
}

/**
 * CSRF for state-changing requests: the Origin must be ours (or the browser must say
 * same-origin), and the double-submit header must match the CSRF cookie when a session exists.
 */
export function checkCsrf(req: NextRequest): boolean {
  const method = req.method.toUpperCase();
  if (method === "GET" || method === "HEAD" || method === "OPTIONS") return true;

  const origin = req.headers.get("origin");
  const fetchSite = req.headers.get("sec-fetch-site");
  const sameOrigin = origin ? origin === req.nextUrl.origin : fetchSite === "same-origin";
  if (!sameOrigin) return false;

  const cookie = req.cookies.get(CSRF_COOKIE)?.value;
  if (!cookie) return !req.cookies.has(REFRESH_COOKIE);
  return req.headers.get(CSRF_HEADER) === cookie;
}

// Concurrent requests carrying the same refresh token share one refresh call. Results are
// kept briefly so a request that raced the cookie update doesn't replay the rotated-out
// token, which FastAPI treats as theft and revokes the session.
const inflight = new Map<string, Promise<TokenPair | null>>();
const REFRESH_REUSE_MS = 10_000;

export function refreshTokens(refreshToken: string): Promise<TokenPair | null> {
  const existing = inflight.get(refreshToken);
  if (existing) return existing;

  const promise = (async () => {
    const res = await fetch(`${API_URL}/v1/auth/refresh`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
      cache: "no-store",
    });
    if (!res.ok) return null;
    return (await res.json()) as TokenPair;
  })();

  inflight.set(refreshToken, promise);
  // then(f, f) rather than finally(): callers handle the rejection; this chain must not re-raise it.
  const forget = () => void setTimeout(() => inflight.delete(refreshToken), REFRESH_REUSE_MS);
  promise.then(forget, forget);
  return promise;
}
