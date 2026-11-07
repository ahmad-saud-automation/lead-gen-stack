/* The login gate for the SCREENS. The engine refuses every /api call without a session on
 * its own (webapp/server.py _login_gate) — that is the real lock. This only sends a browser
 * that is not signed in to /login instead of showing it empty pages full of errors.
 *
 * With no password set and no LEADGEN_REQUIRE_LOGIN, the engine says `required: false` and
 * nothing changes: the app on your own PC stays open, as it always was. */
import { NextResponse, type NextRequest } from "next/server";

const API = (process.env.API_BASE ?? "http://127.0.0.1:8771").replace(/\/$/, "");

export async function middleware(req: NextRequest) {
  let status: { required?: boolean; signed_in?: boolean };
  try {
    const res = await fetch(`${API}/api/auth/status`, {
      headers: { cookie: req.headers.get("cookie") ?? "" },
      cache: "no-store",
    });
    status = await res.json();
  } catch {
    // engine not answering: let the page load and say so itself
    return NextResponse.next();
  }
  if (!status.required || status.signed_in) return NextResponse.next();
  // Built from the Host header the BROWSER sent, never from req.nextUrl's host: `next start`
  // fills that with its own bind address, so a redirect from it sent a browser behind Caddy
  // to https://localhost:3200/login — its own computer (measured 2026-10-04). Next refuses a
  // relative Location, so the address has to be whole.
  const host = req.headers.get("x-forwarded-host") ?? req.headers.get("host") ?? req.nextUrl.host;
  const proto = (req.headers.get("x-forwarded-proto") ?? req.nextUrl.protocol).replace(/:$/, "").split(",")[0];
  const next = encodeURIComponent(req.nextUrl.pathname + req.nextUrl.search);
  return NextResponse.redirect(`${proto}://${host}/login?next=${next}`, 307);
}

export const config = {
  // every page and /legacy; never /api (the engine answers for itself), Next's own files or
  // the login page
  matcher: ["/((?!api|_next/|login|favicon|icon\\.svg|style\\.css|app\\.js).*)"],
};
