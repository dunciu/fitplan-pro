// Coach: the autopilot switch and what it did, the weekly review, and questions.
import React, { useState } from "react";
import { Switch, Text, TextInput, View } from "react-native";
import { api, today } from "./api";
import { ActionCard } from "./Today";
import { Button, Footnote, Group, Header, MD, Row, Section, T, tap, useTheme } from "./ui";

const TONE = { green: "#1A7F4B", yellow: "#A35400", red: "#C02B2B" };
const DECISION = { progress: "Next week steps up a little", maintain: "Next week stays the same", reduce_intensity: "Next week is gentler",
  deload: "Next week is a recovery week", rest_illness: "Next week focuses on rest", pause_and_refer: "Training is paused", complete: "Plan complete" };

export default function Coach({ data, me, reload, toast, setMe }) {
  const t = useTheme();
  const [q, setQ] = useState("");
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState("");
  if (!data) return null;
  const { trends: tr, checkins, actions } = data;
  async function toggle(v) {
    tap();
    const r = await api("/settings", { method: "POST", body: { autopilot: v } });
    setMe({ ...me, autopilot: r.autopilot });
    toast(r.autopilot ? "Autopilot on" : "Autopilot off");
  }
  async function adapt() {
    setBusy("adapt");
    try { const r = await api("/adapt", { method: "POST", body: { date: today() } }); tap("success"); toast(DECISION[r.decision] || "Next week updated"); await reload(); }
    catch (e) { toast(e.message); } finally { setBusy(""); }
  }
  async function ask() {
    if (q.trim().length < 2) return;
    setBusy("ask");
    try { setAnswer((await api("/ask", { method: "POST", body: { question: q.trim() } })).answer); }
    catch (e) { toast(e.message); } finally { setBusy(""); }
  }
  async function undo(id) {
    try { await api("/actions/undo", { method: "POST", body: { id } }); toast("Undone. Original plan restored."); await reload(); } catch (e) { toast(e.message); }
  }
  return (
    <View>
      <Header title="Coach" subtitle="Adapts your plan every day and every week" />
      <Group>
        <Row icon="sparkles" iconBg={t.amber} title="Autopilot" subtitle="Eases your next sessions after a sore day, short sleep or an HRV drop. It never makes training harder."
          right={<Switch testID="autopilot" value={!!me.autopilot} onValueChange={toggle} trackColor={{ true: t.tint }} accessibilityLabel="Autopilot" />} />
      </Group>
      <Footnote>Every change is shown on Today with the reason, and you can undo it.</Footnote>
      {actions.length > 0 && <><Section>Autopilot activity</Section>{actions.slice(0, 8).map(a => <ActionCard key={a.id} a={a} onUndo={undo} />)}</>}

      <Section>Weekly review</Section>
      <Group>
        <Row icon="pulse" iconBg={TONE[tr.readiness]} title={tr.label} subtitle={tr.reasons.join(" ")} />
        <View style={{ padding: 16 }}>
          <Button title="Review and adapt next week" icon="refresh" onPress={adapt} busy={busy === "adapt"} testID="adapt" />
        </View>
      </Group>
      <Footnote>Runs by itself every Sunday evening.</Footnote>

      {checkins.length > 0 && <><Section>Coach updates</Section>
        <Group>{checkins.slice(0, 5).map(c => (
          <View key={c.id} style={{ padding: 16 }}>
            <Text style={[T.footnote, { color: t.mute, fontWeight: "600", marginBottom: 4 }]}>{new Date(c.created).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "short" })}</Text>
            <MD text={c.markdown} /></View>))}</Group></>}

      <Section>Ask your coach</Section>
      <Group>
        <View style={{ padding: 16 }}>
          <TextInput testID="ask" value={q} onChangeText={setQ} placeholder="What if I miss a week?" placeholderTextColor={t.mute} multiline
            style={[T.body, { backgroundColor: t.fill, color: t.ink, borderRadius: 10, padding: 12, minHeight: 48 }]} accessibilityLabel="Question for your coach" />
          <Button title="Ask" onPress={ask} busy={busy === "ask"} style={{ marginTop: 10 }} />
          {!!answer && <View style={{ backgroundColor: t.tintSoft, borderRadius: 12, padding: 12, marginTop: 12 }}><MD text={answer} /></View>}
        </View>
      </Group>
    </View>
  );
}
