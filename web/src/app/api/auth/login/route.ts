import { NextResponse, type NextRequest } from "next/server";

import { API_URL, checkCsrf, setSessionCookies, type TokenPair } from "@/lib/server/session";

export async function POST(req: NextRequest) {
  if (!checkCsrf(req)) {
    return NextResponse.json({ detail: "CSRF check failed" }, { status: 403 });
  }

  const upstream = await fetch(`${API_URL}/v1/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: await req.text(),
    cache: "no-store",
  });

  if (!upstream.ok) {
    return NextResponse.json(await upstream.json(), { status: upstream.status });
  }

  // Tokens go into HttpOnly cookies only; the browser gets no token in the body.
  const res = NextResponse.json({ ok: true });
  setSessionCookies(res, (await upstream.json()) as TokenPair);
  return res;
}
