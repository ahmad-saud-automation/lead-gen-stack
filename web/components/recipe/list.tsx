"use client";

/* Screen B (docs/RECIPE-BUILDER.md §2): the recipe library, inside Settings.
 *
 * A list, not an editor: name · who uses it · when it changed. Copy and delete live here;
 * delete is refused while a campaign still points at it, because that lane would silently
 * fall back to the app's own order on its next run. */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Confirm } from "@/components/modal";
import { Card, Empty, Note, Pill } from "@/components/u";
import { Loading } from "@/components/ui";
import { getJson, postJson } from "@/lib/client-api";
import { flashNote } from "@/lib/nav";
import type { RecipeSaved, RecipesView } from "@/lib/types";
import { personSentence } from "@/lib/words";

export function RecipesSection() {
  const [v, setV] = useState<RecipesView | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [confirm, setConfirm] = useState<{ id: string; name: string } | null>(null);
  const [adding, setAdding] = useState(false);
  const [newName, setNewName] = useState("");

  const load = useCallback(() => {
    getJson<RecipesView>("/recipes").then(setV).catch((e: Error) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  const create = async (copyFrom = "") => {
    const name = newName.trim();
    if (!name) return;
    setBusy("new");
    try {
      const res = await postJson<RecipeSaved>("/recipes/create", { name, copy_from: copyFrom });
      if (!res.ok || !res.id) throw new Error((res.issues ?? []).join(" · ") || "Not created.");
      window.location.assign(`/recipes/${encodeURIComponent(res.id)}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy("");
    }
  };

  const copy = async (id: string, name: string) => {
    setBusy(id);
    try {
      const res = await postJson<RecipeSaved>("/recipes/create", { name: `${name} (copy)`, copy_from: id });
      if (!res.ok || !res.id) throw new Error((res.issues ?? []).join(" · ") || "Not copied.");
      window.location.assign(`/recipes/${encodeURIComponent(res.id)}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy("");
    }
  };

  const remove = async () => {
    if (!confirm) return;
    const { id, name } = confirm;
    setConfirm(null);
    setBusy(id);
    try {
      const res = await postJson<RecipeSaved>("/recipes/delete", { id });
      if (!res.ok) throw new Error((res.issues ?? []).join(" · "));
      flashNote(`${name} deleted.`);
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  };

  return (
    <Card id="s-recipes" title="Finding recipes"
      sub="Who the app emails and in what order. One recipe can be used by several campaigns — changing it changes all of them."
      right={<button type="button" className="u-btn sm" onClick={() => setAdding(!adding)}>{adding ? "Cancel" : "New recipe"}</button>}>

      {error ? <Note tone="bad">{error}</Note> : null}

      {adding ? (
        <div className="u-row" style={{ marginBottom: 12 }}>
          <input className="u-input" aria-label="New recipe name" placeholder="Director waterfall" value={newName}
            autoFocus onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") create(); }} />
          <button type="button" className="u-btn primary" onClick={() => create()} disabled={!newName.trim() || busy === "new"}>
            {busy === "new" ? "Creating…" : "Create"}
          </button>
        </div>
      ) : null}

      {!v ? <Loading rows={3} /> : v.recipes.length === 0 ? (
        <Empty title="No recipes yet">
          <p>
            Without one, every campaign uses the app’s own order: the address already on the row,
            then a guess from the website, then Icypeas. A recipe lets you say who to email and in
            what order instead — for example 1st director, then 2nd director, then the owner.
          </p>
          <button type="button" className="u-btn primary" style={{ marginTop: 10 }} onClick={() => setAdding(true)}>
            New recipe
          </button>
        </Empty>
      ) : (
        <div className="u-reclist">
          {v.recipes.map((r) => (
            <div className="u-recrow" key={r.id}>
              <div className="grow">
                <div className="u-row" style={{ gap: 10 }}>
                  <Link className="u-link" href={`/recipes/${encodeURIComponent(r.id)}`}><b>{r.name}</b></Link>
                  {r.used_by.length
                    ? <Pill tone="live">used by {r.used_by.length}</Pill>
                    : <Pill>not used</Pill>}
                  {r.issues.length ? <Pill tone="bad">needs fixing</Pill> : null}
                </div>
                <div className="u-small u-muted">
                  {r.people.length
                    ? r.people.map((p) => p.label).join(" → ")
                    : "nobody to try yet"}
                </div>
                <div className="u-small u-muted">
                  {r.people.slice(0, 1).map((p, i) => <span key={i}>{personSentence(p)}</span>)}
                </div>
                {r.used_by.length ? (
                  <div className="u-small u-muted">
                    Used by {r.used_by.map((u) => u.name || u.id).join(", ")}
                    {r.updated ? ` · last changed ${r.updated}` : ""}
                  </div>
                ) : r.updated ? <div className="u-small u-muted">Last changed {r.updated}</div> : null}
                {r.issues.length ? <div className="u-small u-badmark">{r.issues[0]}</div> : null}
              </div>
              <div className="u-row" style={{ gap: 6 }}>
                <Link className="u-btn sm" href={`/recipes/${encodeURIComponent(r.id)}`}>Edit</Link>
                <button type="button" className="u-btn sm" onClick={() => copy(r.id, r.name)} disabled={busy === r.id}>Copy</button>
                <button type="button" className="u-btn sm danger" disabled={r.used_by.length > 0 || busy === r.id}
                  title={r.used_by.length ? `Still used by ${r.used_by.map((u) => u.name || u.id).join(", ")}` : undefined}
                  onClick={() => setConfirm({ id: r.id, name: r.name })}>Delete</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {v?.missing.length ? (
        <div style={{ marginTop: 12 }}>
          <Note tone="bad">
            A campaign points at {v.missing.length === 1 ? "a recipe" : "recipes"} that no longer
            exist{v.missing.length === 1 ? "s" : ""}: <b>{v.missing.join(", ")}</b>. Those campaigns
            will not run until you pick another recipe or clear it.
          </Note>
        </div>
      ) : null}

      {confirm ? (
        <Confirm title={`Delete “${confirm.name}”?`} danger confirmLabel="Delete it"
          onConfirm={remove} onClose={() => setConfirm(null)}
          body={<p>No campaign uses it, so nothing stops working. Leads already found are not affected.</p>} />
      ) : null}
    </Card>
  );
}
