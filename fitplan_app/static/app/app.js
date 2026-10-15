"use strict";
const API = "/api/v2";
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
/* Tiny built-in Markdown renderer (headings, bold/italic, lists, tables, paragraphs). Escapes first, so it is safe;
   used when the CDN libraries are unavailable (offline, blocked network). */
function miniMd(src) {
  const inline = t => esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/(^|[^*])\*([^*]+)\*/g, "$1<i>$2</i>").replace(/`([^`]+)`/g, "<code>$1</code>");
  const lines = String(src || "").split(/\r?\n/), out = [];
  let list = null, para = [];
  const flush = () => { if (para.length) { out.push(`<p>${para.map(inline).join(" ")}</p>`); para = []; } if (list) { out.push(`</${list}>`); list = null; } };
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i], h = l.match(/^(#{1,4})\s+(.*)/), li = l.match(/^\s*[-*]\s+(.*)/), ol = l.match(/^\s*\d+\.\s+(.*)/);
    if (/^\s*\|/.test(l)) {
      flush(); const rows = [];
      for (; i < lines.length && /^\s*\|/.test(lines[i]); i++) if (!/^\s*\|[\s:|-]+\|\s*$/.test(lines[i])) rows.push(lines[i].trim().replace(/^\||\|$/g, "").split("|"));
      i--; out.push(`<table>${rows.map((r, k) => `<tr>${r.map(c => k ? `<td>${inline(c.trim())}</td>` : `<th>${inline(c.trim())}</th>`).join("")}</tr>`).join("")}</table>`);
    } else if (h) { flush(); out.push(`<h${Math.min(h[1].length + 1, 4)}>${inline(h[2])}</h${Math.min(h[1].length + 1, 4)}>`); }
    else if (li || ol) { const tag = li ? "ul" : "ol"; if (para.length) { out.push(`<p>${para.map(inline).join(" ")}</p>`); para = []; }
      if (list !== tag) { if (list) out.push(`</${list}>`); out.push(`<${tag}>`); list = tag; } out.push(`<li>${inline((li || ol)[1])}</li>`); }
    else if (!l.trim()) flush();
    else { if (list) { out.push(`</${list}>`); list = null; } para.push(l.trim()); }
  }
  flush(); return out.join("");
}
const md = s => (window.marked && window.DOMPurify) ? DOMPurify.sanitize(marked.parse(s || "")) : miniMd(s);
const iso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const TODAY = () => iso(new Date());
const LABEL = { progress: "Progress", maintain: "Hold steady", reduce_intensity: "Ease the intensity", deload: "Deload week", rest_illness: "Rest and recover", pause_and_refer: "Pause and see a professional", complete: "Plan complete" };
const TONE = { progress: "green", maintain: "green", complete: "green", reduce_intensity: "yellow", deload: "red", rest_illness: "red", pause_and_refer: "red" };

let token = localStorage.getItem("fp_token"), ME = null, tab = "today", planWeek = null, moodSel = null, soreTouched = false, effortSel = null, selDay = null;
let ob = { step: 1, goal: "", age: "", experience: "beginner", weeks: 12, days_per_week: 4, equipment: "", injuries: "", notes: "" };
const TYPE = { easy: "Easy", quality: "Hard", long: "Long", strength: "Strength", cross: "Cross-train", skill: "Skill", mobility: "Mobility" };
const READY = { green: ["Ready to train", "Your recovery looks normal for you."], yellow: ["Take it a bit easier", "Something is off today."], red: ["Recovery comes first", "Your body is asking for rest."] };
const GEAR = `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>`;
const head = (title, sub) => `<header class="top"><div><h1>${title}</h1>${sub ? `<p class="sub">${sub}</p>` : ""}</div>
  <button class="iconbtn" data-act="settings" aria-label="Settings">${GEAR}</button></header>`;
const daysBetween = (a, b) => Math.round((new Date(b + "T00:00:00") - new Date(a + "T00:00:00")) / 864e5);

function toast(m) { const t = $("#toast"); t.textContent = m; t.classList.add("show"); clearTimeout(toast.h); toast.h = setTimeout(() => t.classList.remove("show"), 2600); }

async function api(path, { method = "GET", body, raw } = {}) {
  const headers = { "X-User-Token": token || "" };
  if (body && !raw) headers["Content-Type"] = "application/json";
  const r = await fetch(API + path, { method, headers, body: raw ? body : body ? JSON.stringify(body) : undefined });
  if (r.status === 401) { localStorage.removeItem("fp_token"); location.reload(); throw new Error("Session reset"); }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `Something went wrong (${r.status})`);
  return data;
}
const failView = e => { $("#app").innerHTML = `<div class="notice bad">${esc(e.message || e)}</div><button class="full" data-act="retry">Try again</button>`; };

/* ---------- sheet ---------- */
function openSheet(html) {
  closeSheet();
  document.body.insertAdjacentHTML("beforeend", `<div class="backdrop" data-act="closesheet"></div><div class="sheet" role="dialog" aria-modal="true">
    <div class="grab"></div>${html}</div>`);
  document.body.classList.add("noscroll");
}
function closeSheet() { document.querySelectorAll(".backdrop,.sheet").forEach(x => x.remove()); document.body.classList.remove("noscroll"); }
document.addEventListener("keydown", e => { if (e.key === "Escape") closeSheet(); });

/* ---------- boot ---------- */
async function boot() {
  try {
    if (!token) {
      const r = await fetch(API + "/session", { method: "POST" });
      token = (await r.json()).token; localStorage.setItem("fp_token", token);
    }
    ME = await api("/me");
  } catch (e) { return failView(e); }
  const q = new URLSearchParams(location.search);
  if (q.get("connected")) { toast("WHOOP connected. Your data is syncing."); tab = "settings"; }
  if (q.get("connect_error")) { toast("Couldn't connect: " + q.get("connect_error")); tab = "settings"; }
  if (q.toString()) history.replaceState(null, "", "/");
  route();
  if (ME.reviewing) watchReview();
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
}
function route() {
  if (!ME.plan) { $("#tabs").hidden = true; return (ME.safety && ME.safety.level === "hold") ? viewHold() : viewOnboard(); }
  $("#tabs").hidden = false; setTab(tab);
}
function badge() { $("#badge").hidden = !ME.unseen; }
async function setTab(t) {
  tab = t; badge(); closeSheet();
  document.querySelectorAll("#tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === t));
  $("#app").innerHTML = `<div class="skeleton"></div><div class="skeleton short"></div>`; window.scrollTo(0, 0);
  try { await ({ today: viewToday, plan: viewPlan, trends: viewTrends, coach: viewCoach, settings: viewSettings })[t](); } catch (e) { failView(e); }
}
async function watchReview() {
  if (watchReview.on) return; watchReview.on = true;
  try {
    for (let i = 0; i < 240; i++) {
      await new Promise(r => setTimeout(r, 4000));
      const s = await api("/onboard/status");
      if (!s.running) {
        ME = await api("/me");
        const fin = (s.events || []).find(e => e.stage === "final");
        if (fin && fin.report) toast(`Plan reviewed: ${fin.report.changes.length || "no"} fix${fin.report.changes.length === 1 ? "" : "es"} made`);
        if (ME.plan && ["today", "plan"].includes(tab)) setTab(tab);
        break;
      }
    }
  } catch (e) { /* ignore */ } finally { watchReview.on = false; }
}
const reviewBanner = () => ME.reviewing ? `<div class="notice info"><span class="spin"></span> Your coach team is still reviewing this plan. You can start now; it updates by itself.</div>` : "";

/* ---------- onboarding ---------- */
function viewHold() {
  $("#app").innerHTML = `<div class="hero"><h1>Let's get you checked first</h1></div>
  <div class="notice bad">${esc(ME.safety.message || "A professional should look at this before you start.")}</div>
  <p class="sub">Once you've been cleared, come back and start again.</p>
  <button class="full" data-act="startover">Start again</button>`;
}
const GOALS = [["🏃", "Run my first 5K"], ["🏃", "Run a 10K"], ["🏅", "Run a half marathon"], ["🏊", "Swim 1500 m"], ["🏋️", "Get stronger"], ["🗓️", "Build a routine"], ["🏸", "Badminton season prep"], ["🚴", "Sprint triathlon"]];
function viewOnboard() {
  const s = ob.step;
  let body = "";
  if (s === 1) body = `<h2>What do you want to do?</h2><p class="sub">Pick one or type your own.</p>
    <div class="goalgrid">${GOALS.map(([i, g]) => `<button class="goal ${ob.goal === g ? "on" : ""}" data-act="goalchip" data-v="${esc(g)}"><span>${i}</span>${esc(g)}</button>`).join("")}</div>
    <label for="ob-goal">Your goal</label><input id="ob-goal" value="${esc(ob.goal)}" maxlength="300" placeholder="e.g. run a 10K in the spring">
    <button class="full" data-act="next">Next</button>`;
  if (s === 2) body = `<h2>About you</h2><p class="sub">Used to set a safe starting load.</p>
    <div class="grid2"><div><label for="ob-age">Age</label><input id="ob-age" type="number" inputmode="numeric" min="8" max="100" value="${esc(ob.age)}"></div>
    <div><label for="ob-exp">Experience</label><select id="ob-exp">${["beginner", "intermediate", "advanced"].map(x => `<option ${x === ob.experience ? "selected" : ""}>${x}</option>`).join("")}</select></div>
    <div><label for="ob-weeks">Plan length</label><select id="ob-weeks">${[8, 12, 16, 20].map(x => `<option value="${x}" ${x == ob.weeks ? "selected" : ""}>${x} weeks</option>`).join("")}</select></div>
    <div><label for="ob-days">Days per week</label><select id="ob-days">${[2, 3, 4, 5, 6].map(x => `<option value="${x}" ${x == ob.days_per_week ? "selected" : ""}>${x} days</option>`).join("")}</select></div></div>
    <div class="row"><button class="ghost" data-act="back">Back</button><button data-act="next">Next</button></div>`;
  if (s === 3) body = `<h2>Anything we should know?</h2><p class="sub">Optional, but it makes the plan fit you.</p>
    <label for="ob-eq">Equipment or access</label><input id="ob-eq" value="${esc(ob.equipment)}" placeholder="gym, pool, dumbbells, nothing...">
    <label for="ob-inj">Injuries or health notes</label><textarea id="ob-inj" placeholder="Past injuries, anything that hurts">${esc(ob.injuries)}</textarea>
    <label for="ob-notes">Schedule, sport season, what stopped you before</label><textarea id="ob-notes">${esc(ob.notes)}</textarea>
    <div class="row"><button class="ghost" data-act="back">Back</button><button data-act="build">Build my plan</button></div>`;
  $("#app").innerHTML = `<div class="hero"><img class="logo" src="/app/icon-192.png" alt=""><h1>FitPlan Pro</h1>
    <p class="sub">A research agent, a critic and an editor build your plan. Then your coach adapts it every day.</p></div>
    <div class="progress"><span style="width:${s * 33.4}%"></span></div><div class="card">${body}</div>`;
}
function readOb() {
  const g = id => { const el = $(id); return el ? el.value : null; };
  if (g("#ob-goal") !== null) ob.goal = g("#ob-goal").trim();
  if (g("#ob-age") !== null) { ob.age = g("#ob-age"); ob.experience = g("#ob-exp"); ob.weeks = +g("#ob-weeks"); ob.days_per_week = +g("#ob-days"); }
  if (g("#ob-eq") !== null) { ob.equipment = g("#ob-eq").trim(); ob.injuries = g("#ob-inj").trim(); ob.notes = g("#ob-notes").trim(); }
}
const STAGES = [["safety", "Safety check", "Screens for anything a doctor should see first"], ["research", "Research agent", "Writes your guide and every session"],
  ["critic", "Critic agent", "Hunts for mistakes and unsafe advice"], ["editor", "Editor agent", "Fixes what the critic found"]];
function progressView(state, msgs, draftReady) {
  $("#app").innerHTML = `<div class="hero"><h1>Building your plan</h1><p class="sub">Your agents work in parallel. Usually one to three minutes.</p></div>
  ${draftReady ? `<div class="card ready"><h3>Your first weeks are ready</h3><p class="mute" style="margin:2px 0 0">The critic and editor keep checking in the background and the plan updates itself.</p>
    <button class="full" data-act="opendraft">Start now</button></div>` : ""}
  <div class="card"><ul class="steps-run">${STAGES.map(([k, n, d]) => `<li class="${state[k] || ""}"><span class="ic"></span><div><b>${n}</b>
    <div class="mute" style="font-size:13px">${esc(msgs[k] || d)}</div></div></li>`).join("")}</ul></div>`;
}
async function buildPlan() {
  const state = {}, msgs = {};
  let draftReady = false, opened = false;
  const show = () => { if (!opened) progressView(state, msgs, draftReady); };
  show();
  const body = { goal: ob.goal, age: +ob.age, experience: ob.experience, weeks: ob.weeks, days_per_week: ob.days_per_week, equipment: ob.equipment, injuries: ob.injuries, notes: ob.notes, date: TODAY() };
  buildPlan.open = async () => { opened = true; ME = await api("/me"); ME.reviewing = true; ob.step = 1; tab = "today"; route(); };
  try {
    const res = await fetch(API + "/onboard", { method: "POST", headers: { "X-User-Token": token, "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) { const d = await res.json().catch(() => ({})); throw new Error(d.error || "Please check your answers."); }
    const reader = res.body.getReader(), dec = new TextDecoder(); let buf = "", finalEv = null, errEv = null;
    for (;;) {
      const { done, value } = await reader.read(); if (done) break;
      buf += dec.decode(value, { stream: true }); let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        if (!chunk.startsWith("data: ")) continue;
        const ev = JSON.parse(chunk.slice(6));
        if (ev.stage === "error") { errEv = ev; continue; }
        if (ev.stage === "final") { finalEv = ev; continue; }
        if (ev.stage === "draft") { draftReady = true; show(); continue; }
        if (ev.stage === "safety") { state.safety = "done"; msgs.safety = ev.data.level === "ok" ? "Passed" : ev.data.level === "restricted" ? "Passed with extra safety rules" : "Needs a professional first"; }
        else { state[ev.stage] = ev.status === "done" ? "done" : "run"; if (ev.message) msgs[ev.stage] = ev.message; if (ev.status === "done" && ev.stage === "critic") msgs.critic = `${(ev.data.issues || []).length} issue(s) found`; }
        show();
      }
    }
    ME = await api("/me");
    if (errEv && !errEv.draft_kept) throw new Error(errEv.message);
    if (errEv) toast(errEv.message);
    if (!opened) { ob.step = 1; tab = "today"; route(); if (finalEv && finalEv.status === "ok") toast("Your plan is ready"); }
    else { if (finalEv && finalEv.report) toast(`Plan reviewed: ${finalEv.report.changes.length || "no"} fix${finalEv.report.changes.length === 1 ? "" : "es"} made`); if (["today", "plan"].includes(tab)) setTab(tab); }
  } catch (e) {
    if (opened) return toast(e.message);
    $("#app").innerHTML = `<div class="notice bad">${esc(e.message)}</div><button class="full" data-act="back">Back</button>`;
    ob.step = 3;
  }
}

/* ---------- Autopilot ---------- */
const TOOLNAME = { ease_session: "Eased a session", move_session: "Moved a session", rest_day: "Made a rest day", finish: "Told you", thought: "Thinking" };
function stepsHtml(steps) {
  return `<ul class="steps">${(steps || []).filter(s => s.tool !== "changes").map(s => {
    if (s.tool === "thought") return `<li class="mute">${esc(s.input.text)}</li>`;
    const res = s.result || {}, inp = s.input || {};
    const what = s.tool === "finish" ? "" : s.tool === "move_session" ? `${esc(inp.from_date)} to ${esc(inp.to_date)}` : `${esc(inp.date || "")} ${inp.type ? esc(inp.type) + " " + esc(inp.minutes) + " min" : ""}`;
    return `<li>${esc(TOOLNAME[s.tool] || s.tool)} ${what} ${res.ok ? "✓" : `<span style="color:var(--red)">rejected: ${esc(res.error || "")}</span>`}</li>`;
  }).join("")}</ul>`;
}
function changesHtml(a) {
  const ch = ((a.steps || []).find(s => s.tool === "changes") || {}).input || [];
  return ch.length ? `<ul class="steps">${ch.map(c => `<li><b>${esc(dayName(c.date))}</b>: ${esc(c.from)} becomes ${esc(c.to)}</li>`).join("")}</ul>` : "";
}
function actionCard(a, compact) {
  if (!a) return "";
  if (a.kind === "escalate") return `<div class="notice bad"><b>Your coach paused today's training.</b><br>${esc(a.message)}</div>`;
  if (a.kind === "no_change") return compact ? "" : `<div class="group"><div class="row-item"><b>Coach checked in, ${esc(dayName(a.date))}</b><span class="mute">${esc(a.message)}</span></div></div>`;
  return `<div class="group autopilot"><div class="row-item"><span class="ico" style="background:var(--amber)">✦</span><span class="grow"><b>${a.undone ? "Change undone" : "Your coach adjusted your plan"}</b>
    <span class="mute">${esc(dayName(a.date))}</span></span></div><div class="pad"><p style="margin:4px 0">${esc(a.message)}</p>
    <p class="mute" style="font-size:13px;margin:4px 0">Because: ${esc((a.triggers || []).join(", "))}</p>${changesHtml(a)}
    <details><summary class="mute" style="font-size:13px;cursor:pointer">How the coach decided</summary>${stepsHtml(a.steps)}</details>
    ${a.undone ? "" : `<button class="sec full" data-act="undo" data-v="${a.id}">Undo, I feel fine</button>`}</div></div>`;
}
async function runAutopilot(reasons) {
  $("#app").insertAdjacentHTML("afterbegin", `<div class="card" id="ap-run"><div class="kicker">Autopilot</div><h3>Your coach is adjusting your plan...</h3>
    <p class="mute" style="margin:0;font-size:14px">Because: ${esc(reasons.join(", "))}</p></div>`);
  window.scrollTo(0, 0);
  try {
    const r = await api("/autopilot", { method: "POST", body: { date: TODAY() } });
    if (r.acted && r.action) toast(r.action.kind === "adjusted" ? "Your coach adjusted your plan" : r.action.kind === "escalate" ? "Training paused" : "Coach checked in");
  } catch (e) { toast(e.message); }
}



/* ---------- Today ---------- */
// The screen wears today's session: the hero is filled with the session colour (white text, contrast 5.2-7.3:1).
const FEEL = [["fresh", "Fresh", 1, 5, "☺"], ["normal", "Normal", 3, 4, "–"], ["sore", "Sore", 7, 3, "✚"], ["wrecked", "Wrecked", 9, 2, "▭"]];
const feelOf = l => l.soreness == null ? null : FEEL.reduce((b, f) => Math.abs(f[2] - l.soreness) < Math.abs(b[2] - l.soreness) ? f : b)[0];
const PHASE = { Base: "Building a base", Foundation: "Building a base", Build: "Building up", Intensify: "Building up", Peak: "Peak weeks", Deload: "Recovery week", Taper: "Easing off before the event" };
const phaseName = p => PHASE[p] || (String(p).startsWith("Deload") ? "Recovery week" : p);
const dayName = d => new Date(d + "T00:00:00").toLocaleDateString(undefined, { weekday: "long" });
function sessionCard(s, label, isToday, l) {
  if (!s) return `<section class="dayhero t-rest sess-card" aria-label="${esc(label)}"><p class="hero-kind">${esc(label)}</p><h2>Rest day</h2>
    <p class="hero-effort">Recovery is part of the plan. An easy walk or stretching is fine.</p></section>`;
  const kind = (TYPE[s.type] || s.type);
  return `<section class="dayhero t-${esc(s.type)} sess-card" aria-label="${esc(label)}: ${esc(s.title)}">
    <p class="hero-kind">${esc(label)}, ${esc(kind.toLowerCase())} session</p><h2>${esc(s.title)}</h2>
    <p class="hero-min" aria-label="${esc(s.minutes)} minutes"><b>${esc(s.minutes)}</b> min</p><p class="hero-effort">${esc(s.effort || "")}</p>
    ${s.autopilot ? `<p class="hero-note">✦ Adjusted by your coach</p>` : ""}
    ${!isToday ? "" : l.done === 1 ? `<p class="hero-note"><b>✓ Done. Nice work.</b></p>`
      : `<div class="row"><button class="on-white" data-act="done" data-v="1">✓ Mark done</button><button class="on-color" data-act="done" data-v="0">Skip</button></div>`}
    ${isToday && l.done === 0 ? `<p class="hero-note">Skipped. That's fine; tell your coach how you feel below.</p>` : ""}</section>
    ${(s.details || []).length ? `<h3 class="sect">Steps</h3><ol class="group steps-list t-${esc(s.type)}">${s.details.map(x => `<li>${esc(x)}</li>`).join("")}</ol>` : ""}
    ${s.why ? `<p class="foot">Why: ${esc(s.why)}</p>` : ""}`;
}
async function viewToday() {
  const [t, tr] = await Promise.all([api("/today?date=" + TODAY()), api("/trends?days=28&date=" + TODAY())]);
  const l = t.logged || {};
  if (!selDay || !t.strip.some(d => d.date === selDay)) selDay = TODAY();
  const date = new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
  let h = head("Today", `${esc(date)}${t.week ? `, week ${t.week} of ${ME.plan.weeks}` : ""}`);
  h += reviewBanner();
  if (ME.unseen) h += `<div class="notice warn tap" data-act="tab" data-tab="coach">Your coach has a plan update for next week. Tap to read it.</div>`;
  h += actionCard(t.action, true);
  if (t.complete) h += `<div class="group"><div class="row-item"><b>Plan complete</b><span class="mute">Create a new plan in Settings.</span></div></div>`;
  else if (t.before_start) h += `<div class="group"><div class="row-item"><b>Your plan hasn't started yet</b></div></div>`;
  else {
    h += `<div class="strip">${t.strip.map(d => `<button class="day ${d.date === selDay ? "sel" : ""} ${d.today ? "today" : ""}" data-act="pickday" data-v="${d.date}"
      aria-label="${d.weekday}${d.session ? ", " + esc(TYPE[d.session.type] || d.session.type) : ", rest"}${d.done === 1 ? ", done" : ""}" aria-pressed="${d.date === selDay}">
      <b>${esc(d.weekday[0])}</b><span class="num">${+d.date.slice(8)}</span>
      <span class="dot ${d.session ? "t-" + esc(d.session.type) : ""} ${d.done === 1 ? "done" : d.done === 0 && d.session ? "miss" : ""}"></span></button>`).join("")}</div>`;
    if (selDay === TODAY()) h += sessionCard(t.session, "Today", true, l);
    else {
      const d = t.strip.find(x => x.date === selDay);
      const full = d && d.session ? (await api("/plan")).weeks.find(w => w.week === t.week).sessions.find(s => s.day === d.weekday && s.type !== "mobility") : null;
      h += `<p class="sub"><a href="#" data-act="pickday" data-v="${TODAY()}">Back to today</a></p>` + sessionCard(full, dayName(selDay), false, {});
    }
  }
  const cur = feelOf(l);
  const extra = [l.sleep_h != null && `${(+l.sleep_h).toFixed(1)} h sleep`, l.rhr != null && `RHR ${Math.round(l.rhr)}`, l.hrv != null && `HRV ${Math.round(l.hrv)}`].filter(Boolean).join(", ");
  h += `<h3 class="sect">How do you feel?</h3><div class="feel">${FEEL.map(f => `<button class="${cur === f[0] ? "on" : ""}" data-act="feel" data-v="${f[0]}"
      aria-pressed="${cur === f[0]}"><span aria-hidden="true">${f[4]}</span>${f[1]}</button>`).join("")}</div>
    <div class="group" style="margin-top:10px">
      <button class="row-item tap" data-act="checkin"><span class="ico" style="background:var(--brand)">✎</span><span class="grow"><b>${extra ? "Edit" : "Add"} sleep, heart rate and notes</b>
        <span class="mute">${esc(extra || "Optional. Synced trackers do this for you.")}</span></span><span class="chev">›</span></button>
      ${tr.data_days >= 3 ? `<button class="row-item tap" data-act="tab" data-tab="trends"><span class="ico r-${tr.readiness}">∿</span><span class="grow"><b>${READY[tr.readiness][0]}</b>
        <span class="mute">${esc(tr.reasons[0] || READY[tr.readiness][1])}</span></span><span class="chev">›</span></button>` : ""}
    </div>${t.focus ? `<p class="foot">This week: ${esc(t.focus)}</p>` : ""}`;
  $("#app").innerHTML = h;
  viewToday.log = l;
}
function checkinSheet() {
  const l = viewToday.log || {};
  moodSel = l.mood ?? null; effortSel = l.effort ?? null; soreTouched = l.soreness != null;
  openSheet(`<h2>How are you today?</h2><p class="sub">Leave blank anything you don't know.</p>
  <div class="grid3"><div><label for="ci-sleep">Sleep (h)</label><input id="ci-sleep" type="number" inputmode="decimal" step="0.1" value="${l.sleep_h ?? ""}"></div>
  <div><label for="ci-rhr">Resting HR</label><input id="ci-rhr" type="number" inputmode="numeric" value="${l.rhr ?? ""}"></div>
  <div><label for="ci-hrv">HRV (ms)</label><input id="ci-hrv" type="number" inputmode="decimal" value="${l.hrv ?? ""}"></div></div>
  <label for="ci-sore">Soreness <output id="ci-so">${l.soreness ?? "–"}</output>/10</label><input id="ci-sore" type="range" min="0" max="10" value="${l.soreness ?? 3}">
  <div class="scale"><span>None</span><span>Very sore</span></div>
  <label>Mood</label><div class="seg">${[1, 2, 3, 4, 5].map(n => `<button class="${moodSel === n ? "on" : ""}" data-act="mood" data-v="${n}">${["Low", "Meh", "OK", "Good", "Great"][n - 1]}</button>`).join("")}</div>
  <label>How hard was today's session?</label><div class="seg small">${[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(n => `<button class="${effortSel === n ? "on" : ""}" data-act="effort" data-v="${n}">${n}</button>`).join("")}</div>
  <label for="ci-notes">Anything to tell your coach?</label><input id="ci-notes" maxlength="400" value="${esc(l.notes || "")}" placeholder="Optional">
  <button class="full" data-act="savelog">Save check-in</button>`);
  const r = $("#ci-sore"); r.addEventListener("input", () => { soreTouched = true; $("#ci-so").textContent = r.value; });
}
async function saveLog(extra = {}) {
  const n = id => { const v = $(id) ? $(id).value.trim() : ""; return v === "" ? undefined : Number(v); };
  const body = { date: TODAY(), sleep_h: n("#ci-sleep"), rhr: n("#ci-rhr"), hrv: n("#ci-hrv"), effort: effortSel ?? undefined, mood: moodSel ?? undefined,
    soreness: soreTouched ? n("#ci-sore") : undefined, notes: $("#ci-notes") && $("#ci-notes").value.trim() ? $("#ci-notes").value.trim() : undefined, ...extra };
  return api("/log?date=" + TODAY(), { method: "POST", body });
}

/* ---------- Plan ---------- */
function reportCard(p) {
  const r = p.report;
  if (!r) return p.status === "draft" ? `<div class="card"><div class="kicker">Draft</div><p class="mute" style="margin:0">Being reviewed by the critic and editor.</p></div>` : "";
  const fixes = (r.changes || []).length, crit = r.critic.issues || {};
  return `<div class="card report"><div class="split"><div class="kicker">Checked by your coach team</div><span class="pill green">${esc(p.status === "draft" ? "Draft" : "Reviewed")}</span></div>
    <div class="tiles"><div><b>3</b><span>agents</span></div><div><b>${r.timings_s.total >= 1 ? Math.round(r.timings_s.total) + "s" : "&lt;1s"}</b><span>to build</span></div>
    <div><b>${(crit.high || 0) + (crit.medium || 0) + (crit.low || 0)}</b><span>issues found</span></div><div><b>${fixes}</b><span>fixed</span></div></div>
    <p class="mute" style="font-size:13px;margin:8px 0 0">${r.checks.final_errors === 0 ? "Every week passed the automatic safety and consistency checks." : `${r.checks.final_errors} automatic check(s) still flagged; read those weeks carefully.`}
    ${r.checks.first_pass_errors ? ` ${r.checks.first_pass_errors} problem(s) were caught and repaired before you saw the plan.` : ""}</p>
    ${(r.changes || []).length ? `<details><summary class="mute" style="font-size:13px">What the reviewers changed</summary><ul class="steps">${r.changes.map(c => `<li>${esc(c)}</li>`).join("")}</ul></details>` : ""}
    <div class="split" style="margin-top:10px"><span class="mute" style="font-size:14px">${p.rating ? "Thanks for rating this plan." : "Is this plan right for you?"}</span>
    <div class="thumbs"><button class="${p.rating === 1 ? "on" : ""}" data-act="rate" data-v="1" aria-label="Good plan">👍</button><button class="${p.rating === -1 ? "on" : ""}" data-act="rate" data-v="-1" aria-label="Not right">👎</button></div></div></div>`;
}
async function viewPlan() {
  const p = await api("/plan");
  ME.reviewing = p.reviewing;
  const n = p.weeks.length, cur = Math.min(n, Math.max(1, Math.floor(daysBetween(p.start_date, TODAY()) / 7) + 1));
  if (!planWeek || planWeek > n) planWeek = cur;
  const row = p.outline.find(r => r.week === planWeek), wk = p.weeks.find(w => w.week === planWeek);
  const order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const sessions = wk.sessions.slice().sort((a, b) => order.indexOf(a.day) - order.indexOf(b.day));
  const maxMin = Math.max(...p.outline.map(r => r.minutes));
  $("#app").innerHTML = head("Plan", `${esc(ME.profile ? ME.profile.goal : "")}, ${n} weeks`) + reviewBanner() +
  `<div class="progress labelled"><span style="width:${100 * cur / n}%"></span></div><p class="mute" style="font-size:13px;margin:4px 0 14px">Week ${cur} of ${n}</p>
  ${reportCard(p)}
  <div class="weekbars">${p.outline.map(r => `<button class="wb ${r.week === planWeek ? "on" : ""} ${r.week === cur ? "now" : ""} ${r.deload || r.taper ? "light" : ""}" data-act="week" data-v="${r.week}"
    aria-label="Week ${r.week}, ${esc(phaseName(r.phase))}"><i style="height:${Math.max(18, 100 * r.minutes / maxMin)}%"></i><span>${r.week}${r.adapted ? "•" : ""}</span></button>`).join("")}</div>
  <div class="card"><p class="mute" style="margin:0 0 2px">${esc(phaseName(row.phase))}, about ${row.minutes} minutes in total</p><h2>Week ${planWeek}</h2><p class="mute" style="margin:0">${esc(wk.focus || "")}</p>
    ${row.adapted ? `<div class="notice warn" style="margin:10px 0 0">Adapted by your coach (${esc(LABEL[row.decision] || row.decision)}).</div>` : ""}</div>
  ${sessions.map(s => `<details class="sess t-${esc(s.type)}"><summary><span class="d">${esc(s.day)}</span><span class="t"><b>${esc(s.title)}</b><br>
    <span class="tag"><span class="tdot"></span>${esc(TYPE[s.type] || s.type)}${s.autopilot ? ", adjusted" : ""}</span></span><span class="m">${esc(s.minutes)} min</span></summary>
    <div class="meta" style="margin-top:8px">${esc(s.effort || "")}</div><ul class="steps">${(s.details || []).map(x => `<li>${esc(x)}</li>`).join("")}</ul>${s.why ? `<p class="why">Why: ${esc(s.why)}</p>` : ""}</details>`).join("")}
  <details class="card"><summary><b>Plan guide</b> <span class="mute">exercises, fuel, warning signs</span></summary><div class="md" style="margin-top:10px">${md(p.framework)}</div></details>`;
  const on = document.querySelector(".wb.on"); if (on) on.scrollIntoView({ inline: "center", block: "nearest" });
}

/* ---------- Progress ---------- */
function chart(label, pts, base, unit, dec = 0) {
  const vals = pts.map(p => p.v).filter(v => v != null);
  if (vals.length < 2) return `<div class="card chart"><h3>${label}</h3><div class="empty">Not enough data yet. Check in for a few days or connect your tracker in Settings.</div></div>`;
  const W = 320, H = 96, P = 10;
  let lo = Math.min(...vals, base ?? Infinity), hi = Math.max(...vals, base ?? -Infinity); if (lo === hi) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * .15; lo -= pad; hi += pad;
  const x = i => P + (W - 2 * P) * i / (pts.length - 1), y = v => H - P - (H - 2 * P) * (v - lo) / (hi - lo);
  let d = "", pen = false, dots = "";
  pts.forEach((p, i) => { if (p.v == null) { pen = false; return; } d += `${pen ? "L" : "M"}${x(i).toFixed(1)} ${y(p.v).toFixed(1)} `; pen = true; dots += `<circle cx="${x(i).toFixed(1)}" cy="${y(p.v).toFixed(1)}" r="1.8" fill="var(--brand)"/>`; });
  const last = [...pts].reverse().find(p => p.v != null);
  const bl = base != null ? `<line x1="${P}" x2="${W - P}" y1="${y(base).toFixed(1)}" y2="${y(base).toFixed(1)}" stroke="var(--mute)" stroke-dasharray="4 4" stroke-width="1"/>` : "";
  return `<div class="card chart"><div style="display:flex;justify-content:space-between;align-items:baseline"><h3>${label}</h3><span class="now">${last.v.toFixed(dec)} ${unit}</span></div>
  <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${label} over the last ${pts.length} days">${bl}<path d="${d}" fill="none" stroke="var(--brand)" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>${dots}</svg>
  <div class="legend">Last ${pts.length} days${base != null ? `. The dashed line is your usual (${base.toFixed(dec)} ${unit}).` : ""}</div></div>`;
}

async function viewTrends() {
  const t = await api("/trends?days=28&date=" + TODAY());
  const m = s => (t.metrics.find(x => x.startsWith(s)) || "");
  const sleep = m("Sleep").replace("Sleep ", ""), done = m("Sessions done").replace("Sessions done ", ""), hrv = (m("HRV").match(/\(([^)]+)\)/) || [])[1];
  $("#app").innerHTML = head("Progress", "Compared with your own baseline, never with other people.") +
  `<div class="tiles big"><div><b>${esc(sleep || "–")}</b><span>sleep, last 7 days</span></div><div><b>${esc(hrv || "–")}</b><span>HRV vs baseline</span></div>
    <div><b>${esc(done || "–")}</b><span>sessions done</span></div></div>
  <div class="card"><span class="pill ${t.readiness}">${esc(t.label)}</span><ul class="steps">${t.reasons.map(r => `<li>${esc(r)}</li>`).join("")}</ul></div>
  ${chart("HRV", t.series.hrv, t.baseline.hrv, "ms")}${chart("Resting heart rate", t.series.rhr, t.baseline.rhr, "bpm")}${chart("Sleep", t.series.sleep_h, t.baseline.sleep_h, "h", 1)}
  ${t.data_days < 3 ? `<button class="card cta" data-act="settings"><div><b>Connect your tracker</b><div class="mute" style="font-size:14px">Sync WHOOP or Apple Health, or import a file.</div></div><span class="chev">›</span></button>` : ""}`;
}

/* ---------- Coach ---------- */
async function viewCoach() {
  const [t, c, acts] = await Promise.all([api("/trends?days=28&date=" + TODAY()), api("/checkins"), api("/actions")]);
  if (ME.unseen) { api("/checkins/seen", { method: "POST" }).catch(() => {}); ME.unseen = 0; badge(); }
  $("#app").innerHTML = head("Coach", "Adapts your plan every day and every week.") +
  `<div class="card"><div class="split"><div><h3 style="margin:0">Autopilot</h3>
    <p class="mute" style="margin:2px 0 0;font-size:13px">Eases your next sessions by itself after a sore day, short sleep or an HRV drop. It never makes training harder, and you can undo anything.</p></div>
    <button class="switch ${ME.autopilot ? "on" : ""}" data-act="aptoggle" role="switch" aria-checked="${ME.autopilot}" aria-label="Autopilot">${ME.autopilot ? "On" : "Off"}</button></div></div>
  ${acts.items.length ? `<h3 class="sect">Autopilot activity</h3>` + acts.items.slice(0, 10).map(x => actionCard(x, false)).join("") : ""}
  <h3 class="sect">Weekly review</h3>
  <div class="card"><div class="kicker">Right now</div><span class="pill ${t.readiness}" style="margin:6px 0">${esc(t.label)}</span><ul class="steps">${t.reasons.map(r => `<li>${esc(r)}</li>`).join("")}</ul>
    <p class="mute" style="font-size:13px;margin:0">Runs automatically every Sunday evening.</p><button class="full" data-act="adapt">Adapt next week now</button></div>
  ${c.items.length ? `<h3 class="sect">Coach updates</h3>` + c.items.map(i => `<div class="card"><div class="kicker">${esc(new Date(i.created).toLocaleDateString(undefined, { day: "numeric", month: "short" }))}</div><div class="md">${md(i.markdown)}</div></div>`).join("") : ""}
  <div class="card"><h3>Ask your coach</h3><div class="ask"><input id="ask-q" maxlength="1000" placeholder="What if I miss a week?"><button data-act="ask">Ask</button></div><div id="ans"></div></div>`;
}

/* ---------- Settings ---------- */
async function viewSettings() {
  const p = ME.profile || {}, s = await api("/sync/info");
  const SC = [["steady", "Steady and recovered"], ["overreaching", "Overreaching (HRV falling)"], ["poor_sleep", "Poor sleep"], ["illness", "Illness warning signs"]];
  const ago = x => x ? new Date(x).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "never";
  document.querySelectorAll("#tabs button").forEach(b => b.classList.remove("on"));
  $("#app").innerHTML = `<header class="top"><div><h1>Settings</h1><p class="sub">${esc(p.goal || "")}${p.age ? `, age ${esc(p.age)}` : ""}</p></div>
    <button class="iconbtn" data-act="tab" data-tab="today" aria-label="Close">✕</button></header>
  ${ME.mock_mode ? `<div class="notice warn">Demo mode: the server has no AI key, so plans are placeholders.</div>` : ""}
  <h3 class="sect">Live sync</h3>
  <div class="card"><div class="split"><h3 style="margin:0">WHOOP</h3><span class="pill ${s.whoop.connected ? "green" : ""}">${s.whoop.connected ? "Connected" : "Not connected"}</span></div>
    <p class="mute" style="font-size:14px;margin:4px 0 0">${s.whoop.connected ? `Syncs recovery, HRV, resting HR and sleep every hour. Last sync: ${ago(s.whoop.last_sync)}.`
      : s.whoop.configured ? "Sign in with WHOOP once; your coach then sees each morning's recovery." : "Not set up on this server yet (needs a WHOOP developer app)."}</p>
    ${s.whoop.connected ? `<div class="row"><button class="sec" data-act="whoopsync">Sync now</button><button class="ghost" data-act="whoopoff">Disconnect</button></div>`
      : s.whoop.configured ? `<button class="full" data-act="whoopon">Connect WHOOP</button>` : ""}</div>
  <div class="card"><div class="split"><h3 style="margin:0">Fitbit Air / Google Health</h3><span class="pill ${s.google.connected ? "green" : ""}">${s.google.connected ? "Connected" : "Not connected"}</span></div>
    <p class="mute" style="font-size:14px;margin:4px 0 0">${s.google.connected ? `Syncs resting heart rate, HRV and sleep every ${s.sync_minutes} minutes. Last sync: ${ago(s.google.last_sync)}.`
      : s.google.configured ? "Sign in with the Google account your Fitbit uses. Your coach then sees each night's sleep and recovery." : "Not set up on this server yet (needs a Google Cloud project with the Google Health API)."}</p>
    ${s.google.connected ? `<div class="row"><button class="sec" data-act="connsync" data-v="google">Sync now</button><button class="ghost" data-act="connoff" data-v="google">Disconnect</button></div>`
      : s.google.configured ? `<button class="full" data-act="connon" data-v="google">Connect Google Health</button>` : ""}</div>
  <div class="card"><h3 style="margin:0">Apple Watch / Apple Health</h3>
    <p class="mute" style="font-size:14px;margin:4px 0 8px">Use the iPhone app <b>Health Auto Export</b>: Automations → REST API, paste the URL and add the header below, choose HRV, resting heart rate, steps and sleep, aggregate by day. Last data received: ${ago(s.last_push)}.</p>
    <label>URL</label><div class="copy"><input readonly value="${esc(s.push_url)}" id="push-url"><button class="sec" data-act="copy" data-v="push-url">Copy</button></div>
    <label>Header: Authorization</label><div class="copy"><input readonly value="Bearer ${esc(s.push_key)}" id="push-key"><button class="sec" data-act="copy" data-v="push-key">Copy</button></div>
    <p class="mute" style="font-size:12px;margin:8px 0 0">Keep this key private. <a href="#" data-act="rotate">Make a new key</a> if it leaks.</p></div>
  <div class="card"><h3>Import a file</h3><p class="mute" style="font-size:14px;margin:0 0 8px">Whoop, Oura or Fitbit CSV, or the Apple Health export .zip (Health → profile → Export All Health Data).</p>
    <input id="imp-file" type="file" accept=".csv,.zip,.xml"><button class="full" data-act="import">Import</button></div>
  ${ME.demo_enabled ? `<h3 class="sect">Try it out</h3><div class="card"><p class="mute" style="font-size:14px;margin:0 0 4px">Fill the last 4 weeks with sample data and watch the coach react.</p>${SC.map(([k, n]) => `<button class="sec full" style="margin-top:8px" data-act="seed" data-v="${k}">${esc(n)}</button>`).join("")}</div>` : ""}
  <h3 class="sect">Your iPhone</h3>
  <div class="card"><h3 style="margin:0">Use FitPlan in the iPhone app</h3>
    <p class="mute" style="font-size:14px;margin:4px 0 0">Open the FitPlan app in Expo Go, enter this server's address, then this code. It links your phone to this account.</p>
    <div id="paircode"></div><button class="sec full" data-act="pair">Show a pairing code</button></div>
  <h3 class="sect">Plan</h3>
  <div class="card"><button class="sec full" style="margin:0" data-act="startover">Create a different plan</button></div>
  <div class="card"><h3>Add to your home screen</h3><p class="mute" style="font-size:14px;margin:0"><b>iPhone (Safari):</b> Share → Add to Home Screen.<br><b>Android (Chrome):</b> menu → Install app.</p></div>
  <div class="card"><h3>Privacy</h3><p class="mute" style="font-size:14px;margin:0 0 8px">Your data is stored on the server you run this on, tied to this device. FitPlan gives coaching guidance, not medical advice.</p><button class="danger full" data-act="delete">Delete all my data</button></div>`;
}

/* ---------- events ---------- */
document.addEventListener("click", async e => {
  const el = e.target.closest("[data-act],[data-tab]"); if (!el) return;
  if (el.tagName === "A") e.preventDefault();
  const act = el.dataset.act || "tab", v = el.dataset.v;
  if (act === "closesheet") return closeSheet();
  const busy = (txt) => { el.disabled = true; const old = el.textContent; el.textContent = txt; return () => { el.disabled = false; el.textContent = old; }; };
  const afterData = async res => { if (res && res.autopilot && (res.autopilot.triggered || res.autopilot.screen_note)) { await runAutopilot(res.autopilot.reasons.length ? res.autopilot.reasons : ["your note"]); } };
  try {
    switch (act) {
      case "tab": selDay = null; return setTab(el.dataset.tab);
      case "settings": return setTab("settings");
      case "retry": return boot();
      case "goalchip": ob.goal = v; $("#ob-goal").value = v; document.querySelectorAll(".goal").forEach(b => b.classList.toggle("on", b.dataset.v === v)); return;
      case "next": readOb(); if (ob.step === 1 && ob.goal.length < 3) return toast("Tell us your goal first");
        if (ob.step === 2 && !(+ob.age >= 8 && +ob.age <= 100)) return toast("Enter your age");
        ob.step++; return viewOnboard();
      case "back": readOb(); ob.step = Math.max(1, ob.step - 1); return viewOnboard();
      case "build": readOb(); return buildPlan();
      case "opendraft": return buildPlan.open && buildPlan.open();
      case "startover": if (ME.plan && !confirm("Create a new plan? Your current plan is kept in history but the new one replaces it.")) return;
        ob.step = 1; if (ME.profile) Object.assign(ob, { goal: ME.profile.goal, age: ME.profile.age, experience: ME.profile.experience, weeks: ME.profile.weeks, days_per_week: ME.profile.days_per_week, equipment: ME.profile.equipment, injuries: ME.profile.injuries, notes: "" });
        $("#tabs").hidden = true; return viewOnboard();
      case "pickday": selDay = v; return viewToday();
      case "feel": { const f = FEEL.find(x => x[0] === v); const res = await api("/log?date=" + TODAY(), { method: "POST", body: { date: TODAY(), soreness: f[2], mood: f[3] } });
        toast(`Logged: ${f[1].toLowerCase()}`); await viewToday(); await afterData(res); return viewToday(); }
      case "checkin": return checkinSheet();
      case "mood": moodSel = +v; document.querySelectorAll('[data-act="mood"]').forEach(b => b.classList.toggle("on", +b.dataset.v === moodSel)); return;
      case "effort": effortSel = +v; document.querySelectorAll('[data-act="effort"]').forEach(b => b.classList.toggle("on", +b.dataset.v === effortSel)); return;
      case "done": { const res = await saveLog({ done: +v }); toast(+v ? "Logged. Nice work." : "Skipped"); await afterData(res); return viewToday(); }
      case "savelog": { const r = busy("Saving..."); let res; try { res = await saveLog(); } finally { r(); } closeSheet(); toast("Saved"); await viewToday(); await afterData(res); return viewToday(); }
      case "undo": { const r = busy("Undoing..."); try { await api("/actions/undo", { method: "POST", body: { id: +v } }); toast("Undone. Original plan restored."); } finally { r(); }
        return tab === "coach" ? viewCoach() : viewToday(); }
      case "aptoggle": { const res = await api("/settings", { method: "POST", body: { autopilot: !ME.autopilot } }); ME.autopilot = res.autopilot;
        toast(ME.autopilot ? "Autopilot on" : "Autopilot off"); return viewCoach(); }
      case "week": planWeek = +v; return viewPlan();
      case "rate": await api("/plan/rate", { method: "POST", body: { rating: +v } }); toast(+v === 1 ? "Glad it fits" : "Thanks. Tell your coach what's off in Coach → Ask."); return viewPlan();
      case "adapt": { const r = busy("Adapting..."); try { const res = await api("/adapt", { method: "POST", body: { date: TODAY() } }); ME = await api("/me"); toast(LABEL[res.decision] || "Updated"); } finally { r(); } return viewCoach(); }
      case "ask": { const q = $("#ask-q").value.trim(); if (q.length < 2) return; const r = busy("..."); try { const res = await api("/ask", { method: "POST", body: { question: q } }); $("#ans").innerHTML = `<div class="answer md">${md(res.answer)}</div>`; } finally { r(); } return; }
      case "import": { const f = $("#imp-file").files[0]; if (!f) return toast("Choose a file first"); const r = busy("Importing...");
        let res; try { res = await api("/upload?filename=" + encodeURIComponent(f.name), { method: "POST", body: f, raw: true }); ME = await api("/me"); toast(`Imported ${res.imported_days} days${res.dropped_values ? ` (${res.dropped_values} odd values skipped)` : ""}`); } finally { r(); }
        if (res && res.autopilot && res.autopilot.triggered) { await setTab("today"); await runAutopilot(res.autopilot.reasons); return viewToday(); } return; }
      case "seed": { const r = busy("Adding..."); try { await api("/demo/seed", { method: "POST", body: { scenario: v, date: TODAY() } }); ME = await api("/me"); toast("Demo data added. Check Progress and Coach."); } finally { r(); } return; }
      case "copy": { const inp = $("#" + v); inp.select(); try { await navigator.clipboard.writeText(inp.value); } catch (_) { document.execCommand && document.execCommand("copy"); } return toast("Copied"); }
      case "rotate": if (!confirm("Make a new sync key? The old one stops working.")) return; await api("/sync/rotate", { method: "POST" }); toast("New key made. Update it in Health Auto Export."); return viewSettings();
      case "pair": { const r = await api("/pair/create", { method: "POST" }); $("#paircode").innerHTML = `<div class="paircode">${esc(r.code)}</div>
        <p class="mute" style="font-size:13px;margin:0;text-align:center">Valid for 10 minutes. Server: ${esc(location.origin)}</p>`; return; }
      case "connon": { const r = await api(`/connect/${v}/start`, { method: "POST" }); location.href = r.url; return; }
      case "connsync": { const r = busy("Syncing..."); let res; try { res = await api(`/connect/${v}/sync`, { method: "POST" }); toast(`Synced ${res.imported_days} days`); } finally { r(); }
        if (res && res.autopilot && res.autopilot.triggered) { await setTab("today"); await runAutopilot(res.autopilot.reasons); return viewToday(); } return viewSettings(); }
      case "connoff": if (!confirm("Disconnect?")) return; await api(`/connect/${v}/disconnect`, { method: "POST" }); return viewSettings();
      case "whoopon": { const r = await api("/connect/whoop/start", { method: "POST" }); location.href = r.url; return; }
      case "whoopsync": { const r = busy("Syncing..."); let res; try { res = await api("/connect/whoop/sync", { method: "POST" }); toast(`Synced ${res.imported_days} days`); } finally { r(); } return viewSettings(); }
      case "whoopoff": if (!confirm("Disconnect WHOOP?")) return; await api("/connect/whoop/disconnect", { method: "POST" }); return viewSettings();
      case "delete": if (!confirm("Delete your plan, logs and check-ins permanently?")) return; await api("/me", { method: "DELETE" }); localStorage.removeItem("fp_token"); location.reload(); return;
    }
  } catch (err) { toast(err.message || "Something went wrong"); }
});

boot();
