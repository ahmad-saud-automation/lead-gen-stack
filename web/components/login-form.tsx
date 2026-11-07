"use client";

import { useEffect, useState } from "react";

import { Field, Note } from "@/components/u";
import { getJson, postJson } from "@/lib/client-api";
import { hardGo } from "@/lib/nav";

type Status = { required: boolean; password_set: boolean; signed_in: boolean };

/** The sign-in page: one password, one button. With no login on this computer it goes
 *  straight on to where the person was heading. */
export function LoginForm({ next }: { next: string }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");

  useEffect(() => {
    getJson<Status>("/auth/status")
      .then((s) => {
        if (!s.required || s.signed_in) hardGo(next);
        else setStatus(s);
      })
      .catch((e: Error) => setProblem(e.message));
  }, [next]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setProblem("");
    try {
      const r = await postJson<{ ok: boolean; error?: string }>("/auth/login", { password });
      if (!r.ok) throw new Error(r.error || "Not signed in.");
      hardGo(next);
    } catch (err) {
      setProblem(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  return (
    <div className="u-card">
      <div className="u-brand" style={{ padding: "0 0 16px" }}><i aria-hidden="true">LG</i>Lead Gen Engine</div>
      {status && !status.password_set ? (
        <Note tone="warn">No password is set yet. On the server, in the app folder, run <code>python set_password.py</code>, then reload this page.</Note>
      ) : (
        <form onSubmit={submit} className="u-stack">
          <Field label="Password">
            <input className="u-input" type="password" autoFocus autoComplete="current-password" aria-label="Password"
              value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
          <button type="submit" className="u-btn primary" disabled={busy || !password}>{busy ? "Signing in…" : "Sign in"}</button>
        </form>
      )}
      {problem ? <div style={{ marginTop: 12 }}><Note tone="bad">{problem}</Note></div> : null}
    </div>
  );
}
