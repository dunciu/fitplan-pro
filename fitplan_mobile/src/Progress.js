// Progress: three numbers that matter this week, then each signal against your own baseline.
import React from "react";
import { Text, View } from "react-native";
import { Footnote, Group, Header, Row, Section, T, useTheme } from "./ui";

const TONE = { green: "#1A7F4B", yellow: "#A35400", red: "#C02B2B" };

function Bars({ title, pts, base, unit, dec = 0, color }) {
  const t = useTheme();
  const vals = pts.map(p => p.v).filter(v => v != null);
  if (vals.length < 2) return <Group style={{ marginBottom: 12 }}><Row title={title} subtitle="Not enough data yet. Check in for a few days or connect a tracker in Settings." /></Group>;
  let lo = Math.min(...vals, base ?? Infinity), hi = Math.max(...vals, base ?? -Infinity);
  const pad = (hi - lo) * 0.25 || 1; lo -= pad; hi += pad;
  const H = 96, y = v => H * (v - lo) / (hi - lo);
  const last = [...pts].reverse().find(p => p.v != null);
  const diff = base ? last.v - base : null;
  return (
    <Group style={{ marginBottom: 12 }}>
      <View style={{ padding: 16 }}>
        <Text style={[T.subhead, { color: t.mute, fontWeight: "600" }]}>{title}</Text>
        <View style={{ flexDirection: "row", alignItems: "baseline", gap: 6 }}>
          <Text style={{ color: t.ink, fontSize: 34, fontWeight: "700", fontVariant: ["tabular-nums"] }}>{last.v.toFixed(dec)}</Text>
          <Text style={[T.body, { color: t.mute }]}>{unit}</Text>
          {diff != null && <Text style={[T.subhead, { color: t.mute, marginLeft: 6 }]}>{`${diff >= 0 ? "+" : ""}${diff.toFixed(dec)} vs your usual`}</Text>}
        </View>
        <View style={{ height: H, flexDirection: "row", alignItems: "flex-end", gap: 2, marginTop: 10 }}>
          {base != null && <View style={{ position: "absolute", left: 0, right: 0, bottom: y(base), borderTopWidth: 1, borderStyle: "dashed", borderColor: t.mute }} />}
          {pts.map((p, i) => <View key={i} style={{ flex: 1, height: p.v == null ? 2 : Math.max(3, y(p.v)), borderRadius: 3,
            backgroundColor: p.v == null ? t.fill : i >= pts.length - 7 ? color : t.line }} />)}
        </View>
        <Text style={[T.footnote, { color: t.mute, marginTop: 8 }]}>
          {`Last ${pts.length} days. The last 7 are highlighted` + (base != null ? `; the dashed line is your usual (${base.toFixed(dec)} ${unit}).` : ".")}</Text>
      </View>
    </Group>
  );
}

export default function Progress({ data }) {
  const t = useTheme();
  if (!data) return null;
  const m = s => (data.metrics.find(x => x.startsWith(s)) || "");
  const tiles = [[m("Sleep").replace("Sleep ", "").replace("/night", "") || "–", "sleep a night"],
    [(m("HRV").match(/\(([^)]+)\)/) || [])[1] || "–", "HRV vs usual"], [m("Sessions done").replace("Sessions done ", "") || "–", "sessions done"]];
  return (
    <View>
      <Header title="Progress" subtitle="Compared with your own usual, never other people" />
      <View style={{ flexDirection: "row", gap: 8 }}>{tiles.map(([b, l]) => (
        <View key={l} style={{ flex: 1, backgroundColor: t.card, borderRadius: 12, paddingVertical: 14, paddingHorizontal: 8, alignItems: "center" }}>
          <Text style={{ color: t.ink, fontSize: 22, fontWeight: "700", fontVariant: ["tabular-nums"] }}>{b}</Text>
          <Text style={[T.footnote, { color: t.mute, textAlign: "center" }]}>{l}</Text></View>))}</View>
      <Section>This week</Section>
      <Group><Row icon="pulse" iconBg={TONE[data.readiness]} title={data.label} subtitle={data.reasons.join(" ")} /></Group>
      <Section>Signals</Section>
      <Bars title="Heart rate variability" pts={data.series.hrv} base={data.baseline.hrv} unit="ms" color={t.tint} />
      <Bars title="Resting heart rate" pts={data.series.rhr} base={data.baseline.rhr} unit="bpm" color={t.tint} />
      <Bars title="Sleep" pts={data.series.sleep_h} base={data.baseline.sleep_h} unit="h" dec={1} color={t.tint} />
      <Footnote>HRV going down and resting heart rate going up for several days usually means you need more recovery.</Footnote>
    </View>
  );
}
