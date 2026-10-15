// Questionnaire in three short steps, then the agents build the plan on the server while this screen shows their progress.
import React, { useEffect, useRef, useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { api, today } from "./api";
import { Button, Footnote, Group, Header, Icon, Notice, Row, Section, Seg, T, tap, useTheme } from "./ui";

const GOALS = [["Run my first 5K", "walk"], ["Run a 10K", "speedometer"], ["Run a half marathon", "medal"], ["Swim 1500 m", "water"],
  ["Get stronger", "barbell"], ["Build a routine", "calendar"], ["Badminton season prep", "tennisball"], ["Sprint triathlon", "bicycle"]];
const STAGES = [["safety", "Safety check", "Looks for anything a doctor should see first"], ["research", "Research agent", "Writes your guide and every session"],
  ["critic", "Critic agent", "Looks for mistakes and unsafe advice"], ["editor", "Editor agent", "Fixes what the critic found"]];

export default function Onboard({ onDone, initial }) {
  const t = useTheme();
  const [step, setStep] = useState(1);
  const [f, setF] = useState({ goal: "", age: "", experience: "beginner", weeks: 12, days_per_week: 4, equipment: "", injuries: "", notes: "", ...(initial || {}) });
  const [err, setErr] = useState("");
  const [progress, setProgress] = useState(null);
  const timer = useRef(null);
  const set = (k, v) => setF(x => ({ ...x, [k]: v }));
  const input = [T.body, { color: t.ink, paddingHorizontal: 16, paddingVertical: 14, minHeight: 50 }];
  useEffect(() => () => clearInterval(timer.current), []);

  async function build() {
    setErr("");
    try { await api("/onboard?nostream=1", { method: "POST", body: { ...f, age: +f.age, date: today() } }); }
    catch (e) { return setErr(e.message); }
    setProgress({ events: [], running: true });
    timer.current = setInterval(async () => {
      try {
        const s = await api("/onboard/status");
        setProgress(s);
        if (!s.running) {
          clearInterval(timer.current);
          const bad = s.events.find(e => e.stage === "error" && !e.draft_kept);
          const hold = s.events.find(e => e.stage === "final" && e.status === "hold");
          if (bad) { setErr(bad.message); setProgress(null); } else { tap("success"); onDone(!!hold); }
        }
      } catch (e) { /* keep polling */ }
    }, 1500);
  }

  if (progress) {
    const ev = progress.events || [];
    const state = k => ev.some(e => e.stage === k && e.status === "done") ? "done" : ev.some(e => e.stage === k) ? "run" : "";
    const draft = ev.some(e => e.stage === "draft");
    return (
      <ScrollView contentContainerStyle={{ padding: 16, paddingTop: 28 }}>
        <Header title="Building your plan" subtitle={f.goal} />
        <Text style={[T.body, { color: t.mute, marginBottom: 8 }]}>Your agents work in parallel. This usually takes one to three minutes.</Text>
        {draft && <Group style={{ marginTop: 8 }}><View style={{ padding: 16 }}>
          <Text style={[T.headline, { color: t.ink }]}>Your first weeks are ready</Text>
          <Text style={[T.subhead, { color: t.mute, marginTop: 4 }]}>The critic and editor keep checking in the background and the plan updates by itself.</Text>
          <Button title="Start now" onPress={() => { clearInterval(timer.current); onDone(false, true); }} style={{ marginTop: 12 }} testID="startnow" /></View></Group>}
        <Section>Progress</Section>
        <Group>{STAGES.map(([k, name, desc]) => (
          <Row key={k} title={name} subtitle={desc} right={state(k) === "run" ? <ActivityIndicator color={t.tint} /> :
            <Icon name={state(k) === "done" ? "checkmark-circle" : "ellipse-outline"} size={24} color={state(k) === "done" ? t.tint : t.line} />} />))}</Group>
      </ScrollView>
    );
  }

  return (
    <ScrollView contentContainerStyle={{ padding: 16, paddingTop: 28 }} keyboardShouldPersistTaps="handled">
      <Header title={["What's your goal?", "About you", "Anything else?"][step - 1]} subtitle={`Step ${step} of 3`} />
      <View style={[st.bar, { backgroundColor: t.fill }]}><View style={{ width: `${step * 33.4}%`, height: 6, backgroundColor: t.tint, borderRadius: 3 }} /></View>
      {!!err && <Notice tone="bad" text={err} />}
      {step === 1 && <>
        <View style={st.goals}>{GOALS.map(([g, ic]) => {
          const on = f.goal === g;
          return (
            <Pressable key={g} onPress={() => { tap(); set("goal", g); }} accessibilityRole="button" accessibilityLabel={g} accessibilityState={{ selected: on }}
              style={[st.goal, { backgroundColor: on ? t.tint : t.card }]}>
              <Icon name={ic} size={22} color={on ? t.onTint : t.tint} />
              <Text style={[T.subhead, { color: on ? t.onTint : t.ink, fontWeight: "600", marginTop: 6 }]}>{g}</Text></Pressable>);
        })}</View>
        <Section>Or describe it</Section>
        <Group><TextInput testID="goal" style={input} value={f.goal} onChangeText={v => set("goal", v)} placeholder="e.g. run a 10K in the spring" placeholderTextColor={t.mute} /></Group>
        <Button title="Next" onPress={() => f.goal.trim().length >= 3 ? (setErr(""), setStep(2)) : setErr("Pick or describe a goal first.")} style={{ marginTop: 20 }} testID="next1" />
      </>}
      {step === 2 && <>
        <Section>Age</Section>
        <Group><TextInput testID="age" style={input} value={String(f.age)} onChangeText={v => set("age", v.replace(/\D/g, ""))} keyboardType="number-pad" placeholder="30" placeholderTextColor={t.mute} /></Group>
        <Footnote>Used to set a safe starting load. Under-18s get extra safety rules.</Footnote>
        <Section>Experience</Section>
        <Seg options={[["beginner", "New"], ["intermediate", "Some"], ["advanced", "A lot"]]} value={f.experience} onChange={v => set("experience", v)} />
        <Section>Plan length</Section>
        <Seg options={[[8, "8 wk"], [12, "12 wk"], [16, "16 wk"], [20, "20 wk"]]} value={f.weeks} onChange={v => set("weeks", v)} />
        <Section>Days a week</Section>
        <Seg options={[[2, "2"], [3, "3"], [4, "4"], [5, "5"], [6, "6"]]} value={f.days_per_week} onChange={v => set("days_per_week", v)} />
        <View style={st.row}><Button title="Back" kind="plain" onPress={() => setStep(1)} style={{ flex: 1 }} />
          <Button title="Next" onPress={() => (+f.age >= 8 && +f.age <= 100) ? (setErr(""), setStep(3)) : setErr("Enter your age.")} style={{ flex: 2 }} testID="next2" /></View>
      </>}
      {step === 3 && <>
        <Text style={[T.body, { color: t.mute }]}>All optional, but it makes the plan fit you.</Text>
        <Section>Equipment</Section>
        <Group><TextInput style={input} value={f.equipment} onChangeText={v => set("equipment", v)} placeholder="Gym, pool, dumbbells, nothing…" placeholderTextColor={t.mute} /></Group>
        <Section>Injuries or health notes</Section>
        <Group><TextInput testID="injuries" style={[input, { minHeight: 80 }]} multiline value={f.injuries} onChangeText={v => set("injuries", v)} placeholder="Past injuries, anything that hurts" placeholderTextColor={t.mute} /></Group>
        <Section>Schedule and what stopped you before</Section>
        <Group><TextInput style={[input, { minHeight: 80 }]} multiline value={f.notes} onChangeText={v => set("notes", v)} placeholder="e.g. busy Tuesdays, gave up last time after a cold" placeholderTextColor={t.mute} /></Group>
        <View style={st.row}><Button title="Back" kind="plain" onPress={() => setStep(2)} style={{ flex: 1 }} />
          <Button title="Build my plan" icon="sparkles" onPress={build} style={{ flex: 2 }} testID="build" /></View>
      </>}
    </ScrollView>
  );
}

const st = StyleSheet.create({
  bar: { height: 6, borderRadius: 3, marginBottom: 16, overflow: "hidden" },
  goals: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  goal: { width: "48%", flexGrow: 1, minHeight: 84, borderRadius: 14, padding: 14, justifyContent: "center" },
  row: { flexDirection: "row", gap: 10, marginTop: 24 },
});
