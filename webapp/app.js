"use strict";
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
let runId = "";
let cursor = 0;
let pollTimer = null;

async function api(p, o) {
  const r = await fetch(p, Object.assign({ headers: { "Content-Type": "application/json" } }, o));
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}
const post = (p, b) => api(p, { method: "POST", body: JSON.stringify(b || {}) });
const usd = v => v == null ? "-" : (v >= 0.01 ? "$" + v.toFixed(2) : "$" + Number(v).toFixed(4));
function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
function download(url) { const a = document.createElement("a"); a.href = url; document.body.appendChild(a); a.click(); a.remove(); }

/* theme */
function applyTheme(t) { document.documentElement.dataset.theme = t; const b = $("#themeBtn"); if (b) b.textContent = t === "dark" ? "☀ Light" : "◐ Dark"; }
const themeParam = new URLSearchParams(location.search).get("theme");   // ?theme=light for screenshots
applyTheme(themeParam === "light" || themeParam === "dark" ? themeParam : (localStorage.getItem("lgae_theme") || "dark"));
$("#themeBtn").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  localStorage.setItem("lgae_theme", next); applyTheme(next);
});

/* collapsible sidebar (remembers its state; auto-collapsed on small screens) */
function applyNav(collapsed) {
  document.body.classList.toggle("nav-collapsed", !!collapsed);
  localStorage.setItem("lgae_nav", collapsed ? "1" : "0");
}
applyNav(localStorage.getItem("lgae_nav") === null ? window.innerWidth < 900 : localStorage.getItem("lgae_nav") === "1");
$("#menuBtn").addEventListener("click", () => applyNav(!document.body.classList.contains("nav-collapsed")));
$("#scrim").addEventListener("click", () => applyNav(true));

/* live pipeline bar - reflects the real run, and each step jumps to its tab */
const PIPE = [
  { n: 1, label: "source", tab: "leads", stages: [] },
  { n: 2, label: "organize", tab: "leads", stages: ["organize"] },
  { n: 3, label: "find email", tab: "run", stages: ["gateway", "endole", "pattern", "icypeas", "anymail"] },
  { n: 4, label: "verify", tab: "run", stages: ["verify"] },
  { n: 5, label: "icebreaker", tab: "icebreaker", stages: ["icebreaker"] },
  { n: 6, label: "push", tab: "push", stages: ["push"] },
  { n: 7, label: "track", tab: "dashboard", stages: ["sheet", "done"] },
];
function renderPipeline(state) {
  const s = state || {};
  const stage = s.stage || "";
  const live = s.status === "running";
  const activeIdx = PIPE.findIndex(p => p.stages.includes(stage));
  const host = $("#pipeline");
  host.innerHTML = PIPE.map((p, i) => {
    let cls = "";
    if (activeIdx > -1) cls = i === activeIdx ? "now" + (live ? " live" : "") : (i < activeIdx ? "done" : "");
    else if (s.leads) cls = i === 0 ? "done" : "";
    const count = p.counts ? "" : "";
    return `<button class="pstep ${cls}" data-tab="${p.tab}" title="Go to ${p.tab}">
      <span class="pnum">${p.n}</span>${esc(p.label)}${count}</button>`
      + (i < PIPE.length - 1 ? '<span class="pipe-sep">›</span>' : "");
  }).join("");
}
$("#pipeline").addEventListener("click", e => {
  const b = e.target.closest(".pstep"); if (b) location.hash = b.dataset.tab;
});

/* tabs */
const TABS = ["dashboard", "leads", "icebreaker", "settings", "run", "results", "push", "log", "history", "schedule"];
function showTab(t) {
  $$(".navb").forEach(b => b.classList.toggle("active", b.dataset.tab === t));
  $$(".panel").forEach(p => (p.hidden = p.dataset.panel !== t));
  if (t === "dashboard") loadDashboard();
  if (t === "leads") loadLeads();
  if (t === "icebreaker") loadIcebreaker();
  if (t === "settings") { loadConfig(); loadLedger(); }
  if (t === "run") loadRun();
  if (t === "results") loadResults();
  if (t === "push") loadPush();
  if (t === "log") loadLog();
  if (t === "history") loadHistory();
  if (t === "schedule") loadSchedule();
}
$("#nav").addEventListener("click", e => {
  const b = e.target.closest(".navb"); if (!b) return;
  location.hash = b.dataset.tab;
  if (window.innerWidth < 900) applyNav(true);      // overlay menu closes after a pick
});
window.addEventListener("hashchange", () => { const h = (location.hash || "").replace("#", ""); showTab(TABS.includes(h) ? h : "dashboard"); });

/* Dashboard */
async function loadDashboard() {
  const d = await api("/api/dashboard");
  if (!d || d.status === "none") { $("#dashKpis").innerHTML = tile("No runs yet", "-"); $("#credits").innerHTML = '<span class="muted">-</span>'; $("#funnel").innerHTML = ""; $("#statusBreakdown").innerHTML = ""; $("#dashWhen").textContent = ""; return; }
  const cb = d.credits || { rows: [], total_credits: 0, total_usd: 0 };
  $("#dashKpis").innerHTML = [
    ["Leads in", d.total], ["Emails found", d.found, "good"], ["Pushed", d.pushed],
    ["Held", d.held], ["Credits", cb.total_credits], ["Cost", usd(cb.total_usd)],
  ].map(t => tile(t[0], t[1], t[2])).join("");
  $("#credits").innerHTML = cb.rows.map(r =>
    `<div class="crow"><span class="ctool">${esc(r.tool)}</span><span class="crule">${esc(r.rule)}</span><span class="ccred">${r.credits} cr</span><span class="cusd">${usd(r.usd)}</span></div>`).join("")
    + `<div class="crow total"><span class="ctool">Total</span><span class="crule"></span><span class="ccred">${cb.total_credits} cr</span><span class="cusd">${usd(cb.total_usd)}</span></div>`;
  const max = Math.max(1, ...d.funnel.map(f => f.value));
  $("#funnel").innerHTML = d.funnel.map(f =>
    `<div class="frow${f.final ? " final" : ""}"><span class="flabel">${esc(f.label)}</span>
      <span class="ftrack"><span class="fbar" style="width:${Math.round(f.value / max * 100)}%"></span></span>
      <span class="fval">${f.value}</span></div>`).join("");
  $("#statusBreakdown").innerHTML = d.status_breakdown.map(([s, n]) =>
    `<span class="chip ${s === "email_found" ? "hot" : ""}">${esc(s || "-")} · ${n}</span>`).join("") || '<span class="muted">-</span>';
  $("#dashWhen").textContent = (d.status === "running" ? "running · " : "") + (d.when ? "run " + d.when : "");
}
const tile = (label, val, cls) => `<div class="stat"><span>${label}</span><b class="${cls || ""}">${val}</b></div>`;

/* Leads */
$("#browseBtn").addEventListener("click", () => $("#fileInput").click());
$("#fileInput").addEventListener("change", e => uploadFiles(e.target.files));
const drop = $("#drop");
["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("hot"); }));
["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("hot"); }));
drop.addEventListener("drop", e => uploadFiles(e.dataTransfer.files));
$("#clearLeads").addEventListener("click", async () => { await post("/api/leads/clear"); loadLeads(); });
async function uploadFiles(list) {
  const files = Array.from(list || []).filter(f => /\.csv$/i.test(f.name));
  if (!files.length) return;
  const fd = new FormData(); files.forEach(f => fd.append("files", f));
  $("#dropMeta").textContent = "Uploading…";
  renderLeads(await (await fetch("/api/leads/upload", { method: "POST", body: fd })).json());
}
async function loadLeads() { renderLeads(await api("/api/leads")); }
function renderLeads(v) {
  const sk = v.skipped || {};
  $("#leadStats").innerHTML = [
    ["Firms", v.count || 0], ["Duplicates", sk.duplicate || 0],
    ["Already done", sk.already_processed || 0], ["Suppressed", sk.suppressed || 0],
  ].map(t => tile(t[0], t[1])).join("");
  $("#dropMeta").textContent = (v.files && v.files.length) ? v.rows_in + " rows · " + v.files.join(", ") : "";
  $("#leadsWhen").textContent = (v.ts ? "Imported " + v.ts : "") + (v.count > 25 ? "  ·  showing first 25 of " + v.count : "");
  const tb = $("#leadsTable tbody"); tb.innerHTML = "";
  (v.preview || []).slice(0, 25).forEach(p => {
    const tr = document.createElement("tr");
    const gw = p.gateway && p.gateway !== "none" ? `<span class="warn">${esc(p.gateway)}</span>` : '<span class="muted">none</span>';
    tr.innerHTML = `<td>${esc(p.company)}</td><td>${esc(p.domain) || "-"}</td><td>${esc(p.director) || "-"}</td>
      <td>${gw}</td><td class="${p.no_website ? "warn" : "good"}">${p.no_website ? "no website" : "new"}</td>`;
    tb.appendChild(tr);
  });
}

/* Settings */
$("#modeSeg").addEventListener("click", e => { const b = e.target.closest(".seg-b"); if (b) $$("#modeSeg .seg-b").forEach(x => x.classList.toggle("active", x === b)); });
async function loadConfig() {
  const c = await api("/api/config");
  $$("#modeSeg .seg-b").forEach(x => x.classList.toggle("active", x.dataset.val === (c.pattern_mode || "lean")));
  TOGGLES.forEach(k => { $("#" + k).checked = !!c[k]; });
  const ks = c.keys_set || {};
  KEY_FIELDS.forEach(([sel, f]) => {
    const el = $(sel); el.value = "";
    el.placeholder = ks[f] ? "key saved (" + c[f] + ") - leave blank to keep" : "paste key";
  });
  $("#mvCost").value = c.mv_per_verification_usd ?? 0.00178;
  $("#icypeasCost").value = c.icypeas_usd_per_credit ?? 0;
  $("#anymailCost").value = c.anymailfinder_usd_per_credit ?? 0;
  $("#apolloCost").value = c.apollo_credit_usd ?? 0.0236;
  $("#maxFirms").value = c.max_firms ?? 50;
  $("#apiTries").value = c.api_tries ?? 3;
  $("#apiRetryWait").value = c.api_retry_wait ?? 5;
  $("#verifyDelay").value = c.verify_delay_ms ?? 0;
  $("#icypeasThrottle").value = c.icypeas_throttle_seconds ?? 2;
  $("#instantlyCampaign").value = c.instantly_campaign_id || "";
  $("#pushDelay").value = c.push_delay_seconds ?? 3;
  $("#sheetUrl").value = c.sheet_url || "";
  $("#sheetTab").value = c.sheet_tab || "Combined";
  $("#sheetSa").value = c.sheet_service_account_file || "";
}
const KEY_FIELDS = [["#apiKey", "millionverifier_api_key"], ["#icypeasKey", "icypeas_api_key"],
  ["#anymailKey", "anymailfinder_api_key"], ["#openaiKey", "openai_api_key"],
  ["#instantlyKey", "instantly_api_key"]];
const TOGGLES = ["use_endole", "verify_endole_with_mf", "use_patterns", "use_icypeas",
  "verify_icypeas_with_mf", "use_anymailfinder", "verify_anymailfinder_with_mf",
  "use_icebreaker", "use_openai_echo", "accept_catchall", "block_security_gateways",
  "sheet_writeback", "strict_status", "use_ledger", "retry_not_found"];
$("#saveSettings").addEventListener("click", async () => {
  const patch = {
    pattern_mode: $("#modeSeg .seg-b.active").dataset.val,
    mv_per_verification_usd: Number($("#mvCost").value),
    icypeas_usd_per_credit: Number($("#icypeasCost").value),
    anymailfinder_usd_per_credit: Number($("#anymailCost").value),
    apollo_credit_usd: Number($("#apolloCost").value),
    max_firms: Number($("#maxFirms").value),
    api_tries: Number($("#apiTries").value),
    api_retry_wait: Number($("#apiRetryWait").value),
    verify_delay_ms: Number($("#verifyDelay").value),
    icypeas_throttle_seconds: Number($("#icypeasThrottle").value),
    instantly_campaign_id: $("#instantlyCampaign").value.trim(),
    push_delay_seconds: Number($("#pushDelay").value),
    sheet_url: $("#sheetUrl").value.trim(),
    sheet_tab: $("#sheetTab").value.trim() || "Combined",
    sheet_service_account_file: $("#sheetSa").value.trim(),
  };
  TOGGLES.forEach(k => { patch[k] = $("#" + k).checked; });
  KEY_FIELDS.forEach(([sel, f]) => { const v = $(sel).value.trim(); if (v) patch[f] = v; });
  await post("/api/config", patch);
  $("#settingsSaved").textContent = "Saved ✓"; setTimeout(() => ($("#settingsSaved").textContent = ""), 1500);
  loadConfig();
});

/* Live run */
const STEPS = ["organize", "gateway", "endole", "pattern", "verify", "icypeas", "anymail", "icebreaker", "done"];
// internal stage keys -> what the user actually reads
const STAGE_LABELS = {
  organize: "organize", gateway: "gateway", endole: "existing email", pattern: "patterns",
  verify: "verify", icypeas: "Icypeas", anymail: "Anymailfinder", icebreaker: "icebreaker",
  push: "push", sheet: "sheet", result: "result", done: "done",
};
const stageLabel = s => STAGE_LABELS[s] || s;
$("#runBtn").addEventListener("click", async () => {
  const snap = await post("/api/run/start", { test_mode: $("#testMode").checked });
  if (snap.error) { $("#runMeta").textContent = snap.error; return; }
  runId = snap.run_id; cursor = 0; $("#feed").innerHTML = ""; poll();
});
$("#cancelBtn").addEventListener("click", async () => { if (runId) await post("/api/run/cancel", { run_id: runId }); });
async function loadRun() {
  if (pollTimer) return;
  const s = await api("/api/run/status");
  if (s && s.run_id) { runId = s.run_id; cursor = 0; $("#feed").innerHTML = ""; renderRun(s, true); if (s.status === "running") poll(); }
}
function poll() {
  if (pollTimer) clearInterval(pollTimer);
  const tick = async () => {
    const s = await api("/api/run/status?run_id=" + encodeURIComponent(runId) + "&since=" + cursor);
    renderRun(s, false);
    if (s.status !== "running") { clearInterval(pollTimer); pollTimer = null; loadDashboard(); loadResults(); loadHistory(); }
  };
  pollTimer = setInterval(tick, 350); tick();
}
function renderRun(s, replaceFeed) {
  renderPipeline(s);
  if (!s || s.status === "none") { $("#runMeta").textContent = "Idle."; return; }
  runId = s.run_id || runId;
  const running = s.status === "running";
  $("#cancelBtn").hidden = !running;
  $("#runMeta").textContent = `${s.processed} / ${s.total} leads` + (running ? " · running" : " · " + s.status) +
    (s.skipped_done ? ` · ${s.skipped_done} skipped (already done)` : "") + (s.test_mode ? " · test mode" : "");
  $("#bar").style.width = (s.total ? Math.round(s.processed / s.total * 100) : 0) + "%";
  const c = s.counters || {};
  const cb = s.credits || { total_credits: 0, total_usd: 0 };
  $("#runCounters").innerHTML = [
    ["Found", c.found || 0, "good"], ["Held", c.held || 0, "warn"],
    ["No website", c.no_website || 0], ["Not found", c.not_found || 0],
    ["Credits", cb.total_credits], ["Cost", usd(cb.total_usd)],
  ].map(t => tile(t[0], t[1], t[2])).join("");
  const cur = s.stage || "organize";
  const ci = STEPS.indexOf(cur);
  $("#stepper").innerHTML = STEPS.map((st, i) => {
    const cls = st === cur ? "now" : (running && ci > -1 && i < ci ? "done" : (!running ? "done" : ""));
    return `<span class="stp ${cls}">${esc(stageLabel(st))}</span>` + (i < STEPS.length - 1 ? '<span class="sarrow">›</span>' : "");
  }).join("");
  const feed = $("#feed");
  if (replaceFeed) feed.innerHTML = "";
  (s.events || []).forEach(e => { feed.appendChild(feedLine(e)); cursor = Math.max(cursor, e.seq + 1); });
  if (!feed.children.length) feed.innerHTML = '<div class="empty">No events yet - hit “Run now”.</div>';
  feed.scrollTop = feed.scrollHeight;
}
function feedLine(e) {
  const icon = { success: ["✓", "ok"], fail: ["✗", "no"], held: ["⊘", "hd"], skip: ["▷", "sk"], retry: ["↻", "rn"], info: ["·", "stg"] }[e.status] || ["·", "stg"];
  const div = document.createElement("div"); div.className = "ev";
  div.innerHTML = `<span class="t">${esc(e.ts)}</span> <span class="${icon[1]}">${icon[0]}</span> ${esc(e.company)} · <span class="stg">${esc(stageLabel(e.stage))}</span> ${esc(e.detail)}`;
  return div;
}

/* Results */
async function loadResults() { renderResults(await api("/api/results" + (runId ? "?run_id=" + runId : ""))); }
function renderResults(s) {
  const tb = $("#resultsTable tbody"); tb.innerHTML = "";
  $("#simBanner").hidden = !(s && s.test_mode);
  if (!s || !s.results || s.status === "none") { $("#resultsCount").textContent = "No run yet."; return; }
  runId = s.run_id || runId;
  const found = s.results.filter(r => r.found_email).length;
  $("#resultsCount").textContent = `${found} found · ${s.results.length} leads` + (s.results.length > 40 ? " · showing 40" : "");
  s.results.slice(0, 40).forEach(r => {
    const tr = document.createElement("tr"); tr.className = "rowlink";
    const cls = r.status === "email_found" ? "good" : (r.status === "hold_security_gateway" ? "warn" : (r.found_email ? "" : "bad"));
    const ice = r.icebreaker ? `<span title="${esc(r.icebreaker)}">${esc(r.ice_style || "✓")} · ${esc(r.icebreaker.slice(0, 28))}…</span>` : '<span class="muted">-</span>';
    tr.innerHTML = `<td>${esc(r.company)}</td><td>${esc(r.selected_director) || "-"}</td>
      <td>${esc(r.found_email) || "<span class='muted'>-</span>"}</td><td>${esc(r.email_source) || "-"}</td>
      <td>${esc(r.verification)}</td><td>${ice}</td><td class="${cls}">${esc(r.status)}</td>`;
    tb.appendChild(tr);
    const det = document.createElement("tr"); det.hidden = true;
    const tries = (r.tries || []).map(t => `${t.accepted ? "✓" : "·"} ${t.email} → ${t.verification}`).join("\n") || "no pattern candidates";
    const dirs = ["Oldest Director Name", "Director 2 Name", "Director 3 Name"].map(k => r[k]).filter(Boolean).join(" · ");
    const ib = r.icebreaker ? `\nicebreaker [${r.ice_style}]: ${r.icebreaker}` : "";
    det.innerHTML = `<td colspan="7" class="tries">directors: ${esc(dirs) || "-"}\n${esc(tries)}${esc(ib)}</td>`;
    tb.appendChild(det);
    tr.addEventListener("click", () => (det.hidden = !det.hidden));
  });
}
$("#downloadResults").addEventListener("click", () => download("/api/results/download" + (runId ? "?run_id=" + runId : "")));

/* Icebreaker editor */
const IB_GROUPS = {
  ibOffer: [["O1a", "Offer 1a"], ["O1b", "Offer 1b"], ["O2a", "Offer 2a"], ["O2b", "Offer 2b"], ["O3", "Offer 3 - no company name"]],
  ibDelivered: [["D1", "D1 - soft, names the finding"], ["D2", "D2 - enquiries angle"], ["D2_speed", "D2 speed - used for slow/layout issues"]],
  ibClean: [["CLEAN", "Clean site"]],
};
function ibFields() {
  const t = {};
  Object.values(IB_GROUPS).flat().forEach(([k]) => {
    const el = document.getElementById("ib_" + k);
    if (el) t[k] = el.value;
  });
  return t;
}
async function loadIcebreaker() {
  const d = await api("/api/icebreaker");
  Object.entries(IB_GROUPS).forEach(([host, keys]) => {
    $("#" + host).innerHTML = keys.map(([k, label]) => {
      const custom = (d.customised || []).includes(k);
      return `<div class="fld"><span>${esc(label)} <code>${k}</code>${custom ? ' <span class="warn">edited</span>' : ""}</span>
        <textarea id="ib_${k}" rows="3">${esc(d.templates[k] || "")}</textarea></div>`;
    }).join("");
  });
  previewIcebreaker();
}
async function previewIcebreaker() {
  const d = await post("/api/icebreaker/preview", { templates: ibFields() });
  const probs = (d.problems || []).length
    ? `<div class="bad" style="margin-bottom:8px;">${d.problems.map(esc).join("<br>")}</div>` : "";
  $("#ibPreviews").innerHTML = probs + (d.previews || []).map(p =>
    `<div style="margin-bottom:9px;"><span class="chip">${esc(p.mode)} · ${esc(p.style)}</span>
      <div style="margin-top:4px;">Hi {firstName}, ${esc(p.text)}</div></div>`).join("");
}
$("#ibPreview").addEventListener("click", previewIcebreaker);
$("#ibSave").addEventListener("click", async () => {
  const r = await post("/api/icebreaker", { templates: ibFields() });
  $("#ibMsg").textContent = r.ok ? "Saved ✓" : ((r.problems || ["failed"]).join("; "));
  setTimeout(() => ($("#ibMsg").textContent = ""), 2500);
  if (r.ok) loadIcebreaker();
});
$("#ibReset").addEventListener("click", async () => {
  await post("/api/icebreaker/reset");
  $("#ibMsg").textContent = "Reset to defaults ✓";
  setTimeout(() => ($("#ibMsg").textContent = ""), 2000);
  loadIcebreaker();
});

/* Processed ledger */
async function loadLedger() {
  const s = await api("/api/ledger");
  const bits = Object.entries(s.by_status || {}).map(([k, v]) => `${k || "-"} ${v}`).join(" · ");
  $("#ledgerStats").textContent = s.total
    ? `${s.total} leads recorded (${s.pushed} pushed)` + (bits ? ` - ${bits}` : "")
    : "nothing recorded yet";
}
$("#clearLedger").addEventListener("click", async () => {
  await post("/api/ledger/clear"); loadLedger();
});

/* Push to Instantly */
let pushId = "";
let pushTimer = null;
async function loadPush() {
  const p = await api("/api/push/preview" + (runId ? "?run_id=" + runId : ""));
  $("#pushStats").innerHTML = [
    ["Verified ready", p.ready || 0, "good"],
    ["Instantly key", p.has_key ? "set" : "missing", p.has_key ? "" : "warn"],
    ["Campaign", p.campaign_id ? "set" : "missing", p.campaign_id ? "" : "warn"],
    ["Delay", (p.delay ?? 3) + "s"],
    ["Sheet write-back", p.writeback ? "on" : "off"],
  ].map(t => tile(t[0], t[1], t[2])).join("");
  const tb = $("#pushTable tbody"); tb.innerHTML = "";
  (p.leads || []).forEach(l => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${esc(l.email)}</td><td>${esc(l.first_name) || "-"}</td><td>${esc(l.company_name)}</td>
      <td title="${esc(l.personalization)}">${esc((l.personalization || "").slice(0, 46))}${(l.personalization || "").length > 46 ? "…" : ""}</td>`;
    tb.appendChild(tr);
  });
  if (!tb.children.length) tb.innerHTML = '<tr><td colspan="4" class="muted">Nothing to push - do a Live run first.</td></tr>';
}
async function startPush(live) {
  if (!$("#pushConfirm").checked) { $("#pushMeta").textContent = "Tick the confirm box first."; return; }
  $("#pushFeed").innerHTML = "";
  const s = await post("/api/push/start", { run_id: runId, test_mode: !live, confirm: true });
  if (s.error) { $("#pushMeta").textContent = s.error; return; }
  pushId = s.run_id; pollPush();
}
$("#pushDryBtn").addEventListener("click", () => startPush(false));
$("#pushLiveBtn").addEventListener("click", () => startPush(true));
$("#pushCancelBtn").addEventListener("click", async () => { if (pushId) await post("/api/run/cancel", { run_id: pushId }); });
function pollPush() {
  if (pushTimer) clearInterval(pushTimer);
  let cur = 0;
  const tick = async () => {
    const s = await api("/api/run/status?run_id=" + encodeURIComponent(pushId) + "&since=" + cur);
    const c = s.counters || {};
    const running = s.status === "running";
    $("#pushCancelBtn").hidden = !running;
    $("#pushBar").style.width = (s.total ? Math.round(s.processed / s.total * 100) : 0) + "%";
    $("#pushMeta").textContent = `${s.processed} / ${s.total} · pushed ${c.pushed || 0}` +
      (c.push_failed ? ` · failed ${c.push_failed}` : "") + (c.written_back ? ` · sheet rows ${c.written_back}` : "") +
      (s.test_mode ? " · dry run (nothing sent)" : " · LIVE") + (running ? "" : " · " + s.status);
    const feed = $("#pushFeed");
    (s.events || []).forEach(e => { feed.appendChild(feedLine(e)); cur = Math.max(cur, e.seq + 1); });
    feed.scrollTop = feed.scrollHeight;
    if (!running) { clearInterval(pushTimer); pushTimer = null; loadLog(); }
  };
  pushTimer = setInterval(tick, 400); tick();
}

/* Google Sheet source */
$("#loadSheetBtn").addEventListener("click", async () => {
  $("#sheetMsg").textContent = "Loading…";
  const v = await post("/api/sheets/load");
  if (v.error) { $("#sheetMsg").textContent = v.error; return; }
  $("#sheetMsg").textContent = "Loaded ✓";
  renderLeads(v);
});

/* Schedule */
async function loadSchedule() {
  const s = await api("/api/schedule");
  $("#schedStatus").innerHTML = s.scheduled
    ? `<span class="good">Scheduled</span> · task <code>${esc(s.task)}</code>` +
      (s.next_run ? ` · next run ${esc(s.next_run)}` : "") + (s.status ? ` · ${esc(s.status)}` : "")
    : `Not scheduled yet.`;
}
let schedKind = "minute";
const SCHED_UI = {
  minute: { every: "Every (minutes)", end: true, days: false, hint: "A common cadence is every 30 minutes between 08:00 and 17:30." },
  hourly: { every: "Every (hours)", end: true, days: false, hint: "Runs every N hours. Leave End blank to run all day." },
  daily: { every: "Every (days)", end: false, days: false, hint: "Runs once a day at the start time." },
  weekly: { every: "Every (weeks)", end: false, days: true, hint: "Runs on the chosen weekdays at the start time." },
};
$("#schedKind").addEventListener("click", e => {
  const b = e.target.closest(".seg-b"); if (!b) return;
  $$("#schedKind .seg-b").forEach(x => x.classList.toggle("active", x === b));
  schedKind = b.dataset.kind;
  const u = SCHED_UI[schedKind];
  $("#everyLabel").textContent = u.every;
  $("#endWrap").hidden = !u.end;
  $("#daysWrap").hidden = !u.days;
  $("#schedHint").textContent = u.hint;
  $("#schedEvery").value = schedKind === "minute" ? 30 : 1;
});
$("#schedCreate").addEventListener("click", async () => {
  $("#schedMsg").textContent = "Registering…";
  const days = $$("#schedDays input:checked").map(i => i.value);
  const r = await post("/api/schedule/create", {
    kind: schedKind, every: Number($("#schedEvery").value),
    start: $("#schedStart").value.trim(), end: $("#schedEnd").value.trim(),
    days, test_mode: $("#schedTest").checked,
    from_sheet: $("#schedSheet").checked, push: $("#schedPush").checked,
  });
  $("#schedMsg").textContent = r.ok ? `Scheduled ✓ - ${r.summary}` : (r.error || "failed");
  loadSchedule();
});
$("#schedDelete").addEventListener("click", async () => {
  const r = await post("/api/schedule/delete");
  $("#schedMsg").textContent = r.ok ? "Removed ✓" : (r.error || "failed");
  loadSchedule();
});

/* Log */
let logFilter = "all";
$("#logFilter").addEventListener("click", e => { const b = e.target.closest(".seg-b"); if (!b) return; $$("#logFilter .seg-b").forEach(x => x.classList.toggle("active", x === b)); logFilter = b.dataset.f; loadLog(); });
$("#logSearch").addEventListener("input", () => { clearTimeout(window._lt); window._lt = setTimeout(loadLog, 250); });
$("#logThisRun").addEventListener("change", loadLog);
$("#downloadLog").addEventListener("click", () => download("/api/log/download" + (($("#logThisRun").checked && runId) ? "?run_id=" + runId : "")));
async function loadLog() {
  const rq = ($("#logThisRun").checked && runId) ? "&run_id=" + runId : "";
  const q = "?filter=" + logFilter + "&search=" + encodeURIComponent($("#logSearch").value || "") + rq;
  const d = await api("/api/log" + q);
  $$("#logFilter .seg-b").forEach(b => {
    const n = d.counts[b.dataset.f]; b.textContent = b.dataset.f === "all" ? "All" : b.dataset.f[0].toUpperCase() + b.dataset.f.slice(1) + (n != null ? " " + n : "");
  });
  const tb = $("#logTable tbody"); tb.innerHTML = "";
  (d.events || []).forEach(e => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td class="muted">${esc(e.ts)}</td><td>${esc(e.company)}</td><td>${esc(stageLabel(e.stage))}</td>
      <td class="st-${esc(e.status)}">${esc(e.status)}</td><td>${esc(e.detail)}</td>`;
    tb.appendChild(tr);
  });
  if (!tb.children.length) tb.innerHTML = '<tr><td colspan="5" class="muted">No events.</td></tr>';
}

/* History */
async function loadHistory() {
  const h = await api("/api/history");
  const tb = $("#historyTable tbody"); tb.innerHTML = "";
  (h.runs || []).forEach(r => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${esc(r.when)}${r.test_mode ? " <span class='muted'>· test</span>" : ""}</td><td>${r.leads}</td>
      <td class="good">${r.found}</td><td>${r.held}</td><td>${r.not_found}</td><td>${usd(r.spent_usd)}</td>`;
    tb.appendChild(tr);
  });
  if (!tb.children.length) tb.innerHTML = '<tr><td colspan="6" class="muted">No runs yet.</td></tr>';
}

/* boot */
(async function () {
  renderPipeline(null);
  const s = await api("/api/run/status"); if (s && s.run_id) runId = s.run_id;
  renderPipeline(s);
  const h = (location.hash || "").replace("#", "");
  showTab(TABS.includes(h) ? h : "dashboard");
  // keep the pipeline honest even when you're not sitting on the Live run tab
  setInterval(async () => {
    if (pollTimer || pushTimer) return;                 // an active poller already owns it
    const cur = await api("/api/run/status" + (runId ? "?run_id=" + runId : ""));
    if (cur && cur.status === "running") renderPipeline(cur);
  }, 3000);
})();
