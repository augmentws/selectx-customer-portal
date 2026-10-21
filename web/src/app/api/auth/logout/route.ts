import { NextResponse, type NextRequest } from "next/server";

import { ACCESS_COOKIE, API_URL, checkCsrf, clearSessionCookies } from "@/lib/server/session";

export async function POST(req: NextRequest) {
  if (!checkCsrf(req)) {
    return NextResponse.json({ detail: "CSRF check failed" }, { status: 403 });
  }

  const access = req.cookies.get(ACCESS_COOKIE)?.value;
  if (access) {
    const upstream = await fetch(`${API_URL}/v1/auth/logout`, {
      method: "POST",
      headers: { authorization: `Bearer ${access}` },
      cache: "no-store",
    });
    // 401 means the session is already gone; anything else unexpected is worth surfacing.
    if (!upstream.ok && upstream.status !== 401) {
      console.error(`FastAPI logout failed with ${upstream.status}`);
    }
  }

  const res = new NextResponse(null, { status: 204 });
  clearSessionCookies(res);
  return res;
}
