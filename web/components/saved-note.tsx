"use client";

import { useEffect, useState } from "react";

import { onFlashNote, takeSavedNote, type SavedNote } from "@/lib/nav";

/* A save reloads the page (see lib/nav.ts for why), which throws away the form's own "Saved"
 * message. The note is left in sessionStorage before the reload and shown here afterwards, so a
 * save that worked never looks like a click that did nothing. flashNote() shows one straight
 * away, for a change that needed no reload. */
export function SavedNoteBar() {
  const [note, setNote] = useState<SavedNote | null>(null);

  useEffect(() => {
    setNote(takeSavedNote());
    return onFlashNote(setNote);
  }, []);

  if (!note) return null;
  return (
    <div className={note.tone === "warn" ? "saved-note warn" : "saved-note"} role="status">
      <span className="saved-note-mark" aria-hidden="true">
        {note.tone === "warn" ? "!" : "✓"}
      </span>
      <span className="saved-note-text">{note.text}</span>
      <button type="button" className="saved-note-close" aria-label="Close" onClick={() => setNote(null)}>
        ✕
      </button>
    </div>
  );
}
