import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/* Security headers for every app route. All Alberto routes are never framable,
   stopping clickjacking of one-click actions (audit M7).
   Static assets are excluded from the matcher. */
export const config = { matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"] };

export async function middleware(req: NextRequest) {
  const res = NextResponse.next();
  res.headers.set("X-Content-Type-Options", "nosniff");
  res.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  res.headers.set("Content-Security-Policy", "frame-ancestors 'none'");
  res.headers.set("X-Frame-Options", "DENY");
  return res;
}
