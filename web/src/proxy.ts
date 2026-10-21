import { NextResponse, type NextRequest } from "next/server";

// Coarse route protection only: no session cookie means no point rendering the app area.
// FastAPI still authorizes every request the pages make.
export function proxy(req: NextRequest) {
  if (!req.cookies.has("cp_refresh")) {
    const url = new URL("/login", req.url);
    url.searchParams.set("next", req.nextUrl.pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/operators/:path*", "/companies/:path*", "/change-password"],
};
