/* Browser-side calls to the engine.
 *
 * Paths are RELATIVE on purpose: the browser asks this same site for /api/..., and
 * next.config.mjs passes it through to Python. Do not put an absolute address here — a baked-in
 * http://127.0.0.1:8771 points at the VIEWER's own computer, so the app would work only for
 * whoever is sitting at this one.
 *
 * The engine answers 200 with an {error: "..."} body for expected problems (no campaign,
 * unreadable tab, bad field map) rather than an HTTP error. These helpers throw only when the
 * engine could not answer at all; a screen checks `.error` on what comes back, exactly as V2 did.
 */

export type MaybeError = { error?: string };

async function read<T>(res: Response): Promise<T> {
  const text = await res.text();
  let body: Record<string, unknown>;
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = { error: text.slice(0, 300) };
  }
  if (res.status === 401 && body.login && typeof window !== "undefined") {
    // signed out (expired, or the password was changed elsewhere): back to the login page
    const here = window.location.pathname + window.location.search;
    window.location.assign(`/login?next=${encodeURIComponent(here)}`);
  }
  if (!res.ok) {
    const why = body.error || body.detail || `${res.status} ${res.statusText}`;
    throw new Error(typeof why === "string" ? why : JSON.stringify(why));
  }
  return body as T;
}

function unreachable(): Error {
  return new Error("The engine is not answering. Start it with start-app.bat in the project folder.");
}

export async function getJson<T = unknown>(path: string, params?: Record<string, string>): Promise<T> {
  const q = params ? `?${new URLSearchParams(params)}` : "";
  let res: Response;
  try {
    res = await fetch(`/api${path}${q}`, { cache: "no-store" });
  } catch {
    throw unreachable();
  }
  return read<T>(res);
}

export async function postJson<T = unknown>(path: string, body?: unknown): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body ?? {}),
    });
  } catch {
    throw unreachable();
  }
  return read<T>(res);
}
