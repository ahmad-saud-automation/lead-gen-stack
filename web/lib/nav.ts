/* Navigation after a save, and navigation that only changes the ?query.
 *
 * WHY THIS EXISTS — taken from Icebreaker Studio's lib/nav.ts, where it was measured. Do not
 * "modernise" it back to <Link>, router.push() or router.refresh().
 *
 * In a production build (`next start`), a client-side navigation that keeps the same pathname
 * and only changes the query string is unreliable: the router updates the address bar, fetches
 * the new payload, and then renders the cached tree anyway. `router.refresh()` has the same
 * fault: a value saved on a form still showed the old one until F5. `npm run dev` never shows
 * either, which is what makes them so confusing to chase.
 *
 * A full browser navigation is never wrong, and in a production build a page costs 60-200 ms.
 * Page-to-page links are unaffected and still use <Link>.
 *
 * Rule of thumb: the pathname changes -> <Link>. Only the ?query changes, or a save needs the
 * screen to show the new state -> this.
 */

export type SavedNote = { text: string; tone: "ok" | "warn" };

const NOTE_KEY = "leadgen:saved-note";

function leaveNote(note: SavedNote | string): void {
  const value: SavedNote = typeof note === "string" ? { text: note, tone: "ok" } : note;
  try {
    window.sessionStorage.setItem(NOTE_KEY, JSON.stringify(value));
  } catch {
    // Private mode or storage switched off: the screen still refreshes, only the note is lost.
  }
}

const NOTE_EVENT = "leadgen:note";

/** Show a note now, without reloading: for a change the screen already shows (a campaign
 *  switched on), where a reload would only throw away state such as counts already loaded. */
export function flashNote(note: SavedNote | string): void {
  if (typeof window === "undefined") return;
  const value: SavedNote = typeof note === "string" ? { text: note, tone: "ok" } : note;
  window.dispatchEvent(new CustomEvent<SavedNote>(NOTE_EVENT, { detail: value }));
}

/** Listen for flashNote(). Returns the function that stops listening. */
export function onFlashNote(show: (note: SavedNote) => void): () => void {
  const handler = (e: Event) => show((e as CustomEvent<SavedNote>).detail);
  window.addEventListener(NOTE_EVENT, handler);
  return () => window.removeEventListener(NOTE_EVENT, handler);
}

/** Go to `url` with a real browser navigation, replacing the current document. */
export function hardGo(url: string): void {
  if (typeof window === "undefined") return;
  window.location.assign(url);
}

/** Reload the page on screen, showing `note` once it is back. */
export function reloadWithNote(note: SavedNote | string): void {
  if (typeof window === "undefined") return;
  leaveNote(note);
  window.location.reload();
}

/** Go to another page with a real navigation, showing `note` when it opens. */
export function goWithNote(url: string, note: SavedNote | string): void {
  if (typeof window === "undefined") return;
  leaveNote(note);
  window.location.assign(url);
}

/** The note a save left before reloading, read once. */
export function takeSavedNote(): SavedNote | null {
  try {
    const raw = window.sessionStorage.getItem(NOTE_KEY);
    if (!raw) return null;
    window.sessionStorage.removeItem(NOTE_KEY);
    const note = JSON.parse(raw) as SavedNote;
    return typeof note?.text === "string" ? note : null;
  } catch {
    return null;
  }
}

/** Apply `updates` to the current query string and go there. A null value removes that key. */
export function goWithParams(pathname: string, updates: Record<string, string | null>): void {
  if (typeof window === "undefined") return;
  const next = new URLSearchParams(window.location.search);
  for (const [k, v] of Object.entries(updates)) {
    if (v === null) next.delete(k);
    else next.set(k, v);
  }
  const qs = next.toString();
  hardGo(qs ? `${pathname}?${qs}` : pathname);
}
