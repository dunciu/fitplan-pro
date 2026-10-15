// Plan: where you are in the plan, what the agent team checked, then each week as a list of sessions.
import React, { useState } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";
import { api, today } from "./api";
import { Bullets, Footnote, Group, Header, Icon, MD, Notice, Pill, Row, Section, T, phaseName, sessionOf, tap, useTheme } from "./ui";

const ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const DAYNAME = { Mon: "Monday", Tue: "Tuesday", Wed: "Wednesday", Thu: "Thursday", Fri: "Friday", Sat: "Saturday", Sun: "Sunday" };

function Report({ p, onRate }) {
  const t = useTheme();
  const r = p.report;
  if (!r) return p.status === "draft" ? <Notice tone="info" text="This is a draft. The critic and editor are still checking it." /> : null;
  const issues = Object.values(r.critic.issues || {}).reduce((a, b) => a + b, 0), fixes = (r.changes || []).length;
  const secs = r.timings_s.total >= 1 ? `${Math.round(r.timings_s.total)} seconds` : "under a second";
  return (
    <Group>
      <Row icon="shield-checkmark" iconBg={t.green} title="Checked by your coach team"
        subtitle={`Built in ${secs}. The critic found ${issues} issue${issues === 1 ? "" : "s"} and ${fixes} ${fixes === 1 ? "was" : "were"} fixed.`} />
      <Row title={r.checks.final_errors === 0 ? "Every week passed the safety and consistency checks" : `${r.checks.final_errors} check(s) still flagged`}
        right={<Pill text={r.checks.final_errors === 0 ? "Passed" : "Review"} tone={r.checks.final_errors === 0 ? "green" : "yellow"} />} />
      <Row title={p.rating ? "Thanks for rating this plan" : "Is this plan right for you?"}
        right={<View style={{ flexDirection: "row", gap: 8 }}>{[[1, "thumbs-up"], [-1, "thumbs-down"]].map(([v, ic]) => (
          <Pressable key={v} onPress={() => { tap(); onRate(v); }} accessibilityRole="button" accessibilityLabel={v === 1 ? "Good plan" : "Not right for me"}
            accessibilityState={{ selected: p.rating === v }} style={[st.thumb, { backgroundColor: p.rating === v ? t.tint : t.fill }]}>
            <Icon name={ic} size={18} color={p.rating === v ? t.onTint : t.ink} /></Pressable>))}</View>} />
    </Group>
  );
}

export default function Plan({ data, me, reload, toast }) {
  const t = useTheme();
  const [week, setWeek] = useState(null);
  const [open, setOpen] = useState({});
  const [guide, setGuide] = useState(false);
  if (!data) return null;
  const p = data;
  const n = p.weeks.length;
  const cur = Math.min(n, Math.max(1, Math.floor((new Date(today() + "T00:00:00") - new Date(p.start_date + "T00:00:00")) / 864e5 / 7) + 1));
  const w = week || cur;
  const row = p.outline.find(r => r.week === w), wk = p.weeks.find(x => x.week === w);
  const max = Math.max(...p.outline.map(r => r.minutes));
  const sessions = wk.sessions.slice().sort((a, b) => ORDER.indexOf(a.day) - ORDER.indexOf(b.day));
  async function rate(v) { await api("/plan/rate", { method: "POST", body: { rating: v } }); toast(v === 1 ? "Glad it fits" : "Thanks. Tell your coach what's off in Coach."); reload(); }

  return (
    <View>
      <Header title="Plan" subtitle={me.profile ? me.profile.goal : ""} />
      <View style={{ flexDirection: "row", justifyContent: "space-between", marginBottom: 6 }}>
        <Text style={[T.subhead, { color: t.ink, fontWeight: "600" }]}>{`Week ${cur} of ${n}`}</Text>
        <Text style={[T.subhead, { color: t.mute }]}>{n - cur === 0 ? "Final week" : `${n - cur} week${n - cur === 1 ? "" : "s"} to go`}</Text>
      </View>
      <View style={[st.prog, { backgroundColor: t.fill }]}><View style={{ width: `${100 * cur / n}%`, height: 8, backgroundColor: t.tint, borderRadius: 4 }} /></View>
      {p.reviewing && <Notice tone="info" text="Still being reviewed. It updates by itself." />}
      <Report p={p} onRate={rate} />

      <Section>Weeks</Section>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ gap: 8, alignItems: "flex-end", height: 104, paddingRight: 8 }}>
        {p.outline.map(r => {
          const on = r.week === w;
          return (
            <Pressable key={r.week} onPress={() => { tap(); setWeek(r.week); }} accessibilityRole="button" testID={"week-" + r.week}
              accessibilityLabel={`Week ${r.week}, ${phaseName(r.phase)}, about ${r.minutes} minutes`} accessibilityState={{ selected: on }}
              style={{ width: 34, height: "100%", justifyContent: "flex-end", alignItems: "center" }}>
              <View style={{ width: "100%", height: `${Math.max(16, 72 * r.minutes / max)}%`, borderRadius: 8,
                backgroundColor: on ? t.tint : r.week === cur ? t.tintSoft : t.fill, borderWidth: r.week === cur && !on ? 2 : 0, borderColor: t.tint }} />
              <Text style={[T.footnote, { color: on ? t.ink : t.mute, fontWeight: on ? "700" : "400", marginTop: 4 }]}>{r.week}</Text>
            </Pressable>);
        })}
      </ScrollView>
      <Footnote>Shorter bars are lighter weeks: every fourth week eases off, and event plans taper at the end.</Footnote>

      <Section>{`Week ${w}`}</Section>
      <Text style={[T.subhead, { color: t.mute, marginHorizontal: 4, marginTop: -4, marginBottom: 8 }]}>{`${phaseName(row.phase)}, about ${row.minutes} minutes in total. ${wk.focus || ""}`}</Text>
      {row.adapted && <Notice text="Your coach adapted this week to your recent data." />}
      <Group>
        {sessions.map((s, i) => {
          const k = `${w}-${i}`, kind = sessionOf(s.type);
          return (
            <View key={k}>
              <Row icon={kind.icon} iconBg={kind.color} title={s.title} subtitle={`${DAYNAME[s.day] || s.day}, ${kind.label.toLowerCase()}${s.autopilot ? ", adjusted" : ""}`}
                value={`${s.minutes} min`} onPress={() => setOpen(o => ({ ...o, [k]: !o[k] }))} testID={"sess-" + i}
                right={<Icon name={open[k] ? "chevron-up" : "chevron-down"} size={18} color={t.mute} />} />
              {open[k] && <View style={{ paddingHorizontal: 16, paddingBottom: 14, paddingLeft: 58 }}>
                <Text style={[T.subhead, { color: t.mute }]}>{s.effort}</Text>
                <Bullets items={s.details || []} />
                {!!s.why && <Text style={[T.footnote, { color: t.mute, marginTop: 4 }]}>{"Why: " + s.why}</Text>}
              </View>}
            </View>);
        })}
      </Group>

      <Section>Guide</Section>
      <Group>
        <Row icon="book" iconBg={t.blue} title="Exercises, fuel and warning signs" onPress={() => setGuide(!guide)}
          right={<Icon name={guide ? "chevron-up" : "chevron-down"} size={18} color={t.mute} />} />
        {guide && <View style={{ padding: 16 }}><MD text={p.framework} /></View>}
      </Group>
    </View>
  );
}

const st = StyleSheet.create({
  prog: { height: 8, borderRadius: 4, overflow: "hidden", marginBottom: 16 },
  thumb: { width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center" },
});
