// Today: the screen opens in the colour of today's session. One tap tells the coach how you feel; details are optional.
import React, { useState } from "react";
import { Modal, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { api, today } from "./api";
import { Bullets, Button, Footnote, Group, Header, Icon, Notice, Row, Section, Seg, T, dayName, sessionOf, tap, useTheme } from "./ui";

const READY = { green: ["Ready to train", "#1A7F4B"], yellow: ["Take it a bit easier", "#A35400"], red: ["Recovery comes first", "#C02B2B"] };
const MOODS = [[1, "Low"], [2, "Meh"], [3, "OK"], [4, "Good"], [5, "Great"]];
// One-tap check-in: how people actually describe a morning, mapped to the numbers the coach uses.
const FEEL = [["fresh", "Fresh", 1, 5, "happy"], ["normal", "Normal", 3, 4, "remove-circle"], ["sore", "Sore", 7, 3, "bandage"], ["wrecked", "Wrecked", 9, 2, "battery-dead"]];
const feelOf = log => (log.soreness == null ? null : FEEL.reduce((best, f) => (Math.abs(f[2] - log.soreness) < Math.abs(best[2] - log.soreness) ? f : best))[0]);

export function ActionCard({ a, onUndo, busy }) {
  const t = useTheme();
  const [open, setOpen] = useState(false);
  if (!a || a.kind === "no_change") return null;
  if (a.kind === "escalate") return <Notice tone="bad" text={"Your coach paused today's training. " + a.message} />;
  const changes = ((a.steps || []).find(s => s.tool === "changes") || {}).input || [];
  const steps = (a.steps || []).filter(s => s.tool !== "changes");
  return (
    <Group style={{ marginBottom: 16 }}>
      <Row icon="sparkles" iconBg={t.amber} title={a.undone ? "Change undone" : "Your coach eased your plan"} subtitle={`Because: ${(a.triggers || []).join(", ")}`} />
      <View style={{ paddingHorizontal: 16, paddingVertical: 12 }}>
        <Text style={[T.body, { color: t.ink }]}>{a.message}</Text>
        {changes.length > 0 && <Bullets items={changes.map(c => `${dayName(c.date)}: ${c.from} becomes ${c.to}`)} />}
        <Pressable onPress={() => setOpen(!open)} accessibilityRole="button" style={{ minHeight: 44, justifyContent: "center" }}>
          <Text style={[T.subhead, { color: t.tint, fontWeight: "600" }]}>{open ? "Hide how the coach decided" : "How the coach decided"}</Text></Pressable>
        {open && <Bullets color={t.mute} items={steps.map(s => s.tool === "thought" ? s.input.text :
          `${{ ease_session: "Eased a session", move_session: "Moved a session", rest_day: "Made a rest day", finish: "Told you" }[s.tool] || s.tool}` +
          `${s.input && s.input.date ? " on " + dayName(s.input.date) : ""}${s.result ? (s.result.ok ? ", accepted" : ", rejected: " + s.result.error) : ""}`)} />}
        {!a.undone && onUndo && <Button title="Undo, I feel fine" kind="secondary" onPress={() => onUndo(a.id)} busy={busy} style={{ marginTop: 8 }} testID="undo" />}
      </View>
    </Group>
  );
}

// The hero: filled with the session's colour. The minutes are the one big thing on the screen.
function Hero({ s, label, isToday, log, onDone }) {
  const kind = s ? sessionOf(s.type) : sessionOf("rest");
  return (
    <View style={[st.hero, { backgroundColor: kind.color }]} testID="hero">
      <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
        <Icon name={kind.icon} size={16} color="#FFFFFF" />
        <Text style={[T.subhead, st.heroText, { fontWeight: "600" }]}>{s ? `${label}, ${kind.label.toLowerCase()} session` : label}</Text>
      </View>
      {s ? <>
        <Text style={[T.title2, st.heroText, { marginTop: 8 }]}>{s.title}</Text>
        <View style={{ flexDirection: "row", alignItems: "baseline", marginTop: 2 }}>
          <Text style={[st.heroText, st.minutes]} accessibilityLabel={`${s.minutes} minutes`}>{s.minutes}</Text>
          <Text style={[T.title3, st.heroText, { marginLeft: 6, opacity: 0.9 }]}>min</Text>
        </View>
        <Text style={[T.body, st.heroText, { opacity: 0.92 }]}>{s.effort}</Text>
        {s.autopilot && <View style={st.adjusted}><Icon name="sparkles" size={14} color="#FFFFFF" /><Text style={[T.footnote, st.heroText]}>Adjusted by your coach</Text></View>}
        {isToday && (log.done === 1
          ? <View style={[st.adjusted, { marginTop: 14 }]}><Icon name="checkmark-circle" size={18} color="#FFFFFF" /><Text style={[T.headline, st.heroText]}>Done. Nice work.</Text></View>
          : <View style={{ flexDirection: "row", gap: 10, marginTop: 16 }}>
            <Button title="Mark done" kind="white" color={kind.color} icon="checkmark" onPress={() => onDone(1)} style={{ flex: 1.4 }} testID="done" />
            <Button title="Skip" kind="onColor" onPress={() => onDone(0)} style={{ flex: 1 }} /></View>)}
        {isToday && log.done === 0 && <Text style={[T.footnote, st.heroText, { marginTop: 8 }]}>Skipped. That's fine; tell your coach how you feel below.</Text>}
      </> : <>
        <Text style={[T.title2, st.heroText, { marginTop: 8 }]}>Rest day</Text>
        <Text style={[T.body, st.heroText, { opacity: 0.92, marginTop: 4 }]}>Recovery is part of the plan. An easy walk or stretching is fine.</Text>
      </>}
    </View>
  );
}

function DetailsSheet({ visible, log, onClose, onSave }) {
  const t = useTheme();
  const [f, setF] = useState({});
  const [busy, setBusy] = useState(false);
  const v = k => (f[k] !== undefined ? f[k] : log[k] ?? null);
  const input = [st.input, { color: t.ink, backgroundColor: t.fill }];
  const num = (k, x) => setF(o => ({ ...o, [k]: x === "" ? null : x.replace(",", ".") }));
  async function save() {
    setBusy(true);
    const body = {};
    for (const k of ["sleep_h", "rhr", "hrv"]) if (f[k] != null && f[k] !== "") body[k] = Number(f[k]);
    for (const k of ["soreness", "mood", "effort"]) if (f[k] != null) body[k] = f[k];
    if (f.notes && f.notes.trim()) body.notes = f.notes.trim();
    try { await onSave(body); setF({}); } finally { setBusy(false); }
  }
  return (
    <Modal visible={visible} animationType="slide" presentationStyle="pageSheet" onRequestClose={onClose}>
      <View style={{ flex: 1, backgroundColor: t.bg }}>
        <View style={[st.sheetBar, { borderBottomColor: t.line, backgroundColor: t.card }]}>
          <Pressable onPress={onClose} accessibilityRole="button" style={st.barBtn}><Text style={[T.body, { color: t.tint }]}>Cancel</Text></Pressable>
          <Text style={[T.headline, { color: t.ink }]}>Check-in</Text>
          <Pressable onPress={save} accessibilityRole="button" accessibilityLabel="Save check-in" testID="savelog" style={st.barBtn}>
            <Text style={[T.headline, { color: t.tint, textAlign: "right" }]}>{busy ? "Saving" : "Save"}</Text></Pressable>
        </View>
        <ScrollView contentContainerStyle={{ padding: 16, paddingBottom: 40 }} keyboardShouldPersistTaps="handled">
          <Text style={[T.subhead, { color: t.mute, marginBottom: 12 }]}>Leave blank anything you don't know. Synced trackers fill these in for you.</Text>
          <Group>
            {[["sleep_h", "Sleep", "hours"], ["rhr", "Resting heart rate", "bpm"], ["hrv", "HRV", "ms"]].map(([k, label, unit]) => (
              <Row key={k} title={label} right={<View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                <TextInput testID={"ci-" + k} style={input} keyboardType="decimal-pad" value={v(k) == null ? "" : String(v(k))} onChangeText={x => num(k, x)}
                  placeholder="–" placeholderTextColor={t.mute} accessibilityLabel={label} />
                <Text style={[T.subhead, { color: t.mute, width: 40 }]}>{unit}</Text></View>} />))}
          </Group>
          <Section>{`Soreness${v("soreness") != null ? `: ${v("soreness")} out of 10` : ""}`}</Section>
          <Seg small options={[0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(n => [n, String(n)])} value={v("soreness")} onChange={x => setF(o => ({ ...o, soreness: x }))} />
          <Section>Mood</Section>
          <Seg options={MOODS} value={v("mood")} onChange={x => setF(o => ({ ...o, mood: x }))} />
          <Section>How hard was today's session?</Section>
          <Seg small options={[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(n => [n, String(n)])} value={v("effort")} onChange={x => setF(o => ({ ...o, effort: x }))} />
          <Section>Note for your coach</Section>
          <TextInput testID="ci-notes" style={[input, { width: "100%", textAlign: "left", minHeight: 80, paddingTop: 12 }]} multiline
            value={f.notes ?? log.notes ?? ""} onChangeText={x => setF(o => ({ ...o, notes: x }))} placeholder="Optional, e.g. left calf feels tight" placeholderTextColor={t.mute} />
          <Footnote>If you mention chest pain, fainting or similar, your coach pauses training and points you to a doctor.</Footnote>
        </ScrollView>
      </View>
    </Modal>
  );
}

export default function Today({ data, me, reload, setTab, toast }) {
  const t = useTheme();
  const [sel, setSel] = useState(null);
  const [sheet, setSheet] = useState(false);
  const [working, setWorking] = useState("");
  const [busy, setBusy] = useState("");
  if (!data) return null;
  const { day: d, trends: tr, plan } = data;
  const log = d.logged || {};
  const selDay = sel && d.strip.some(x => x.date === sel) ? sel : today();
  const isToday = selDay === today();
  const dateLine = new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });

  async function afterData(res) {
    const ap = res && res.autopilot;
    if (ap && (ap.triggered || ap.screen_note)) {
      setWorking((ap.reasons || []).join(", ") || "your note");
      try {
        const r = await api("/autopilot", { method: "POST", body: { date: today() } });
        if (r.acted && r.action) { tap("medium"); toast(r.action.kind === "adjusted" ? "Your coach eased your plan" : r.action.kind === "escalate" ? "Training paused" : "Coach checked in"); }
      } catch (e) { toast(e.message); } finally { setWorking(""); }
    }
    await reload();
  }
  const post = body => api("/log?date=" + today(), { method: "POST", body: { date: today(), ...body } });
  async function feel(f) {
    setBusy(f[0]);
    try { const r = await post({ soreness: f[2], mood: f[3] }); tap("success"); toast(`Logged: ${f[1].toLowerCase()}`); await afterData(r); }
    catch (e) { toast(e.message); } finally { setBusy(""); }
  }
  async function saveDetails(body) { const r = await post(body); setSheet(false); tap("success"); toast("Check-in saved"); await afterData(r); }
  async function undo(id) {
    setBusy("undo");
    try { await api("/actions/undo", { method: "POST", body: { id } }); toast("Undone. Original plan restored."); await reload(); }
    catch (e) { toast(e.message); } finally { setBusy(""); }
  }
  async function done(v) { const r = await post({ done: v }); if (v) tap("success"); toast(v ? "Logged. Nice work." : "Skipped"); await afterData(r); }

  let s = d.session, label = "Today";
  if (!isToday) {
    const sd = d.strip.find(x => x.date === selDay);
    const wk = plan && plan.weeks.find(w => w.week === d.week);
    s = sd && sd.session && wk ? wk.sessions.find(x => x.day === sd.weekday && x.type !== "mobility") : null;
    label = new Date(selDay + "T00:00:00").toLocaleDateString(undefined, { weekday: "long" });
  }
  const current = feelOf(log);
  const extra = [log.sleep_h != null && `${Number(log.sleep_h).toFixed(1)} h sleep`, log.rhr != null && `RHR ${Math.round(log.rhr)}`,
    log.hrv != null && `HRV ${Math.round(log.hrv)}`].filter(Boolean).join(", ");

  return (
    <View>
      <Header title="Today" subtitle={dateLine + (d.week ? `, week ${d.week} of ${me.plan.weeks}` : "")} />
      {me.reviewing && <Notice tone="info" text="Your coach team is still reviewing this plan. Start now; it updates by itself." />}
      {!!working && <Notice tone="info" icon="sparkles" text={`Your coach is looking at your check-in (${working})…`} />}
      {me.unseen > 0 && <Notice text="Your coach has a plan update for next week. Tap to read it." onPress={() => setTab("coach")} />}
      <ActionCard a={d.action} onUndo={undo} busy={busy === "undo"} />

      {d.complete ? <Group><Row icon="trophy" title="Plan complete" subtitle="Create a new plan in Settings." /></Group> : <>
        <View style={st.strip}>{d.strip.map(x => {
          const on = x.date === selDay, c = x.session ? sessionOf(x.session.type).color : t.line;
          return (
            <Pressable key={x.date} onPress={() => { tap(); setSel(x.date); }} accessibilityRole="button" testID={"day-" + x.weekday}
              accessibilityLabel={`${x.weekday}, ${x.session ? sessionOf(x.session.type).label : "rest"}${x.done === 1 ? ", done" : ""}`}
              accessibilityState={{ selected: on }} style={st.day}>
              <Text style={[T.caption, { color: x.today ? t.tint : t.mute, fontWeight: "700" }]}>{x.weekday[0]}</Text>
              <View style={[st.dayNum, on && { backgroundColor: x.today ? t.tint : t.ink }]}>
                <Text style={[T.headline, { color: on ? (x.today ? t.onTint : t.bg) : t.ink }]}>{Number(x.date.slice(8))}</Text></View>
              {x.done === 1 ? <Icon name="checkmark-circle" size={12} color={c} /> :
                <View style={[st.dot, { backgroundColor: x.session ? c : "transparent", borderColor: c, opacity: x.done === 0 && x.session ? 0.35 : 1 }]} />}
            </Pressable>);
        })}</View>
        {!isToday && <Pressable onPress={() => setSel(today())} accessibilityRole="button" style={{ minHeight: 44, justifyContent: "center", marginTop: -6 }}>
          <Text style={[T.subhead, { color: t.tint, fontWeight: "600" }]}>Back to today</Text></Pressable>}
        <Hero s={s} label={label} isToday={isToday} log={log} onDone={done} />
        {s && (s.details || []).length > 0 && <>
          <Section>Steps</Section>
          <Group>{s.details.map((x, i) => (
            <View key={i} style={{ flexDirection: "row", gap: 12, paddingVertical: 12, paddingHorizontal: 16, alignItems: "flex-start" }}>
              <View style={[st.stepNum, { backgroundColor: sessionOf(s.type).color }]}><Text style={[T.footnote, { color: "#FFFFFF", fontWeight: "700" }]}>{i + 1}</Text></View>
              <Text style={[T.body, { color: t.ink, flex: 1 }]}>{x}</Text></View>))}
          </Group>
          {!!s.why && <Footnote>{"Why: " + s.why}</Footnote>}
        </>}
      </>}

      <Section>How do you feel?</Section>
      <View style={{ flexDirection: "row", gap: 8 }}>{FEEL.map(f => {
        const on = current === f[0];
        return (
          <Pressable key={f[0]} onPress={() => feel(f)} accessibilityRole="button" accessibilityLabel={f[1]} accessibilityState={{ selected: on }} testID={"feel-" + f[0]}
            style={[st.feel, { backgroundColor: on ? t.tint : t.card }]}>
            <Icon name={f[4]} size={22} color={on ? t.onTint : t.tint} />
            <Text style={[T.subhead, { color: on ? t.onTint : t.ink, fontWeight: "600", marginTop: 4 }]}>{busy === f[0] ? "…" : f[1]}</Text>
          </Pressable>);
      })}</View>
      <Group style={{ marginTop: 10 }}>
        <Row icon="create" title={extra ? "Edit sleep, heart rate and notes" : "Add sleep, heart rate and notes"} subtitle={extra || "Optional. Synced trackers do this for you."}
          onPress={() => setSheet(true)} chevron testID="checkin" />
        {tr.data_days >= 3 && <Row icon="pulse" iconBg={READY[tr.readiness][1]} title={READY[tr.readiness][0]} subtitle={tr.reasons[0]} onPress={() => setTab("trends")} chevron />}
      </Group>
      {!!d.focus && <Footnote>{"This week: " + d.focus}</Footnote>}
      <DetailsSheet visible={sheet} log={log} onClose={() => setSheet(false)} onSave={saveDetails} />
    </View>
  );
}

const st = StyleSheet.create({
  hero: { borderRadius: 22, padding: 20, marginTop: 4 },
  heroText: { color: "#FFFFFF" },
  minutes: { fontSize: 72, lineHeight: 80, fontWeight: "800", letterSpacing: -2, fontVariant: ["tabular-nums"] },
  adjusted: { flexDirection: "row", alignItems: "center", gap: 6, marginTop: 10 },
  strip: { flexDirection: "row", justifyContent: "space-between", marginBottom: 12 },
  day: { flex: 1, alignItems: "center", gap: 4, minHeight: 64, paddingVertical: 2 },
  dayNum: { width: 36, height: 36, borderRadius: 18, alignItems: "center", justifyContent: "center" },
  dot: { width: 7, height: 7, borderRadius: 4, borderWidth: 1 },
  stepNum: { width: 24, height: 24, borderRadius: 12, alignItems: "center", justifyContent: "center", marginTop: -1 },
  feel: { flex: 1, minHeight: 72, borderRadius: 14, alignItems: "center", justifyContent: "center", paddingVertical: 10 },
  input: { minWidth: 64, borderRadius: 8, paddingHorizontal: 10, paddingVertical: 8, fontSize: 17, textAlign: "right" },
  sheetBar: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 8, minHeight: 56, borderBottomWidth: 1 },
  barBtn: { minWidth: 72, minHeight: 44, justifyContent: "center", paddingHorizontal: 8 },
});
