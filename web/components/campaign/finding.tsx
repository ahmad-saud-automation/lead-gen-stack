"use client";

/* Section 2 of a campaign — "How it finds emails".
 *
 * ONLY the dropdown is a campaign setting; the ladder itself lives in the recipe, on its
 * own page. That is deliberate: one recipe serves several campaigns, so editing it here
 * would let "Save campaign" quietly rewrite how four other lanes work. What this section
 * shows of the recipe is read-only, with an Edit button that says who else it changes. */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Field, Note, Step } from "@/components/u";
import { getJson, postJson } from "@/lib/client-api";
import type { CampaignRaw, RecipeSaved, RecipesView } from "@/lib/types";
import { personSentence } from "@/lib/words";

export function FindingSection({
  c, set, n = 2,
}: {
  c: CampaignRaw;
  set: (patch: Partial<CampaignRaw>) => void;
  n?: number;
}) {
  const [v, setV] = useState<RecipesView | null>(null);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  const load = useCallback(() => {
    getJson<RecipesView>("/recipes").then(setV).catch(() => setV({ recipes: [] } as unknown as RecipesView));
  }, []);
  useEffect(load, [load]);

  const chosen = (c.recipe ?? "").trim();
  const rec = v?.recipes.find((r) => r.id === chosen);
  const missing = !!chosen && !!v && !rec;

  const create = async () => {
    const nm = name.trim();
    if (!nm) return;
    setBusy(true);
    setProblem("");
    try {
      const res = await postJson<RecipeSaved>("/recipes/create", { name: nm });
      if (!res.ok || !res.id) throw new Error((res.issues ?? []).join(" · ") || "Not created.");
      window.location.assign(`/recipes/${encodeURIComponent(res.id)}`);
    } catch (e) {
      setProblem(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <Step n={n} id="sec-finding" title="How it finds emails" question="Who does it email, and in what order?">
      <div className="u-fgrid two">
        <Field label="Finding recipe"
          hint={<>A recipe says who to try and in what order. Manage them in <Link className="u-link" href="/settings#s-recipes">Settings</Link>.</>}>
          <select className="u-input" aria-label="Finding recipe" value={chosen}
            onChange={(e) => set({ recipe: e.target.value })}>
            <option value="">The app’s own order (no recipe)</option>
            {missing ? <option value={chosen}>{chosen} — no longer exists</option> : null}
            {(v?.recipes ?? []).map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}{r.used_by.length > 1 ? ` — shared by ${r.used_by.length} campaigns` : ""}
              </option>
            ))}
          </select>
        </Field>
      </div>

      {problem ? <div style={{ marginTop: 10 }}><Note tone="bad">{problem}</Note></div> : null}

      {missing ? (
        <div style={{ marginTop: 12 }}>
          <Note tone="bad">
            This campaign points at a recipe called <b>{chosen}</b> that no longer exists. It will not
            run until you pick another one, or choose “The app’s own order”.
          </Note>
        </div>
      ) : null}

      {!chosen && !missing ? (
        <div style={{ marginTop: 12 }}>
          <Note>
            <b>The app’s own order:</b> the address already on the row → a guess from the website →
            Icypeas → Anymailfinder. It emails the one best person per row. Make a recipe when you
            want to say who to try, in what order — for example 1st director, then 2nd director,
            then the owner.
          </Note>
          <div className="u-row" style={{ marginTop: 10 }}>
            {adding ? (
              <>
                <input className="u-input" aria-label="New recipe name" placeholder="Director waterfall"
                  value={name} autoFocus onChange={(e) => setName(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") create(); }} />
                <button type="button" className="u-btn primary" onClick={create} disabled={!name.trim() || busy}>
                  {busy ? "Creating…" : "Create and edit"}
                </button>
                <button type="button" className="u-btn sm" onClick={() => setAdding(false)}>Cancel</button>
              </>
            ) : (
              <button type="button" className="u-btn" onClick={() => setAdding(true)}>New recipe…</button>
            )}
          </div>
        </div>
      ) : null}

      {rec ? (
        <div className="u-recipe-card" style={{ marginTop: 12 }}>
          <div className="u-row" style={{ justifyContent: "space-between", alignItems: "flex-start" }}>
            <div>
              <b className="u-ink">{rec.people.map((p) => p.label).join(" → ") || "nobody to try yet"}</b>
              {rec.people.length ? (
                <ol className="u-small u-muted u-recsteps">
                  {rec.people.map((p, i) => <li key={i}>{p.label}: {personSentence(p)}</li>)}
                </ol>
              ) : null}
              <div className="u-small u-muted" style={{ marginTop: 6 }}>
                Writes only to <b className="u-ink">{rec.write_columns.join(", ")}</b> — nothing else on your sheet is touched.
              </div>
              {rec.used_by.length > 1 ? (
                <div className="u-small u-muted">
                  Shared with {rec.used_by.filter((u) => u.id !== c.id).map((u) => u.name || u.id).join(", ")} — editing it changes them too.
                </div>
              ) : null}
              {rec.issues.length ? <div className="u-small u-badmark" style={{ marginTop: 6 }}>{rec.issues[0]}</div> : null}
            </div>
            <Link className="u-btn sm" href={`/recipes/${encodeURIComponent(rec.id)}`}>Edit recipe</Link>
          </div>
        </div>
      ) : null}
    </Step>
  );
}
