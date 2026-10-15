// Design system for the iPhone app.
// Idea: the app wears today's session. Each session type owns a colour; the Today hero is filled with it.
// Everything else is quiet and native: iOS grouped backgrounds, inset grouped lists, the system font (so Dynamic Type
// works), 17 pt body text, sentence-case labels, 44 pt minimum touch targets, filled icons when selected.
// Every colour pairing below meets WCAG AA (4.5:1) for normal text.
import React, { createContext, useContext } from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, View } from "react-native";
import { Ionicons } from "@expo/vector-icons";
import * as Haptics from "expo-haptics";

const LIGHT = { bg: "#F2F2F7", card: "#FFFFFF", ink: "#000000", mute: "#6C6C70", line: "#D1D1D6", fill: "#E9E9EE", tint: "#0B7350", onTint: "#FFFFFF",
  tintSoft: "#E3F1EA", green: "#1A7F4B", amber: "#A35400", red: "#C02B2B", blue: "#2453B3", greenbg: "#E3F3E9", amberbg: "#FBEFDD", redbg: "#FBE6E6", bluebg: "#E6EDFA" };
const DARK = { bg: "#000000", card: "#1C1C1E", ink: "#FFFFFF", mute: "#A1A1A6", line: "#38383A", fill: "#2C2C2E", tint: "#3CCB91", onTint: "#00160C",
  tintSoft: "#123526", green: "#4FD08A", amber: "#F2A64F", red: "#FF8A80", blue: "#8DB0FF", greenbg: "#123020", amberbg: "#33260F", redbg: "#3A1C1C", bluebg: "#18233D" };

// Session colours carry white text (contrast 5.2-7.3:1).
export const SESSION = {
  easy: { color: "#1F7A52", label: "Easy", icon: "walk" },
  quality: { color: "#B84A0C", label: "Hard", icon: "flash" },
  long: { color: "#2453B3", label: "Long", icon: "map" },
  strength: { color: "#6B3AB3", label: "Strength", icon: "barbell" },
  cross: { color: "#0A7480", label: "Cross-training", icon: "bicycle" },
  skill: { color: "#A8306B", label: "Skill", icon: "tennisball" },
  mobility: { color: "#5B5F66", label: "Mobility", icon: "body" },
  rest: { color: "#5B5F66", label: "Rest", icon: "moon" },
};
export const sessionOf = type => SESSION[type] || SESSION.rest;
// Plain-language names for plan phases (beginners don't know "deload" or "taper").
const PHASE = { Base: "Building a base", Foundation: "Building a base", Build: "Building up", Intensify: "Building up", Peak: "Peak weeks",
  Deload: "Recovery week", Taper: "Easing off before the event" };
export const phaseName = p => PHASE[p] || (String(p).startsWith("Deload") ? "Recovery week" : p);
export const dayName = iso => new Date(iso + "T00:00:00").toLocaleDateString(undefined, { weekday: "long" });
export const TYPE_COLOR = Object.fromEntries(Object.entries(SESSION).map(([k, v]) => [k, v.color]));
export const TYPE_LABEL = Object.fromEntries(Object.entries(SESSION).map(([k, v]) => [k, v.label]));
export const themeFor = scheme => (scheme === "dark" ? DARK : LIGHT);
export const Theme = createContext(LIGHT);
export const useTheme = () => useContext(Theme);
export const tap = (kind = "light") => {
  try {
    if (kind === "success") Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success);
    else Haptics.impactAsync(kind === "medium" ? Haptics.ImpactFeedbackStyle.Medium : Haptics.ImpactFeedbackStyle.Light);
  } catch (e) { /* haptics are optional */ }
};
export const Icon = ({ name, size = 20, color, style }) => <Ionicons name={name} size={size} color={color} style={style} />;

// --- type scale (iOS text styles) ---------------------------------------------------------------------------------
export const T = StyleSheet.create({
  largeTitle: { fontSize: 34, lineHeight: 41, fontWeight: "700", letterSpacing: 0.4 },
  title2: { fontSize: 22, lineHeight: 28, fontWeight: "700" },
  title3: { fontSize: 20, lineHeight: 25, fontWeight: "600" },
  headline: { fontSize: 17, lineHeight: 22, fontWeight: "600" },
  body: { fontSize: 17, lineHeight: 22 },
  subhead: { fontSize: 15, lineHeight: 20 },
  footnote: { fontSize: 13, lineHeight: 18 },
  caption: { fontSize: 12, lineHeight: 16 },
});

export function Header({ title, subtitle, right }) {
  const t = useTheme();
  return (
    <View style={{ flexDirection: "row", alignItems: "flex-end", marginBottom: 14, minHeight: 44 }}>
      <View style={{ flex: 1 }}>
        {!!subtitle && <Text style={[T.subhead, { color: t.mute, fontWeight: "600" }]}>{subtitle}</Text>}
        <Text style={[T.largeTitle, { color: t.ink }]} accessibilityRole="header">{title}</Text>
      </View>
      {right}
    </View>
  );
}
export function H2({ children, style }) { const t = useTheme(); return <Text style={[T.title2, { color: t.ink, marginBottom: 6 }, style]}>{children}</Text>; }
export function H3({ children, style }) { const t = useTheme(); return <Text style={[T.headline, { color: t.ink, marginBottom: 4 }, style]}>{children}</Text>; }
export function P({ children, mute, small, style }) {
  const t = useTheme();
  return <Text style={[small ? T.footnote : T.body, { color: mute ? t.mute : t.ink }, style]}>{children}</Text>;
}
// Section title above a group: sentence case, like the Health and Fitness apps.
export function Section({ children, action }) {
  const t = useTheme();
  return <View style={{ flexDirection: "row", alignItems: "baseline", marginTop: 22, marginBottom: 8, marginHorizontal: 4 }}>
    <Text style={[T.title3, { color: t.ink, flex: 1 }]} accessibilityRole="header">{children}</Text>{action}</View>;
}
export function Footnote({ children }) { const t = useTheme(); return <Text style={[T.footnote, { color: t.mute, marginHorizontal: 16, marginTop: 6 }]}>{children}</Text>; }

// Inset grouped list: one container, rows separated by hairlines (iOS Settings / Health pattern).
export function Group({ children, style }) {
  const t = useTheme();
  const kids = React.Children.toArray(children).filter(Boolean);
  return (
    <View style={[{ backgroundColor: t.card, borderRadius: 12, overflow: "hidden" }, style]}>
      {kids.map((c, i) => <View key={i}>{c}{i < kids.length - 1 && <View style={{ height: StyleSheet.hairlineWidth || 1, backgroundColor: t.line, marginLeft: 16 }} />}</View>)}
    </View>
  );
}
export function Row({ icon, iconBg, title, subtitle, value, onPress, chevron, testID, right, children }) {
  const t = useTheme();
  const body = (
    <View style={{ flexDirection: "row", alignItems: "center", minHeight: 48, paddingVertical: 10, paddingHorizontal: 16, gap: 12 }}>
      {!!icon && <View style={{ width: 30, height: 30, borderRadius: 8, backgroundColor: iconBg || t.tint, alignItems: "center", justifyContent: "center" }}>
        <Icon name={icon} size={17} color="#FFFFFF" /></View>}
      <View style={{ flex: 1 }}>
        <Text style={[T.body, { color: t.ink }]}>{title}</Text>
        {!!subtitle && <Text style={[T.footnote, { color: t.mute, marginTop: 2 }]}>{subtitle}</Text>}
        {children}
      </View>
      {!!value && <Text style={[T.body, { color: t.mute }]}>{value}</Text>}
      {right}
      {chevron && <Icon name="chevron-forward" size={18} color={t.mute} />}
    </View>
  );
  return onPress ? <Pressable onPress={onPress} testID={testID} accessibilityRole="button" accessibilityLabel={title}
    style={({ pressed }) => ({ backgroundColor: pressed ? t.fill : "transparent" })}>{body}</Pressable> : <View testID={testID}>{body}</View>;
}

export function Button({ title, onPress, kind = "primary", busy, disabled, style, testID, icon, color }) {
  const t = useTheme();
  const bg = { primary: color || t.tint, secondary: t.tintSoft, plain: "transparent", danger: t.redbg, onColor: "rgba(255,255,255,0.18)", white: "#FFFFFF" }[kind];
  const fg = { primary: t.onTint, secondary: t.tint, plain: t.tint, danger: t.red, onColor: "#FFFFFF", white: color || t.tint }[kind];
  return (
    <Pressable testID={testID} accessibilityRole="button" accessibilityLabel={title} onPress={busy || disabled ? undefined : () => { tap(); onPress && onPress(); }}
      style={({ pressed }) => [st.btn, { backgroundColor: bg, opacity: disabled ? 0.45 : pressed ? 0.75 : 1 }, style]}>
      {busy ? <ActivityIndicator color={fg} /> : <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
        {!!icon && <Icon name={icon} size={18} color={fg} />}<Text style={[T.headline, { color: fg }]}>{title}</Text></View>}
    </Pressable>
  );
}
export function Pill({ text, tone }) {
  const t = useTheme();
  const c = { green: [t.greenbg, t.green], yellow: [t.amberbg, t.amber], red: [t.redbg, t.red] }[tone] || [t.fill, t.mute];
  return <View style={[st.pill, { backgroundColor: c[0] }]}><Text style={[T.footnote, { color: c[1], fontWeight: "600" }]}>{text}</Text></View>;
}
export function Notice({ text, tone = "warn", onPress, icon }) {
  const t = useTheme();
  const c = { warn: [t.amberbg, t.amber, "alert-circle"], bad: [t.redbg, t.red, "medkit"], good: [t.greenbg, t.green, "checkmark-circle"], info: [t.bluebg, t.blue, "sync"] }[tone];
  const body = <View style={[st.notice, { backgroundColor: c[0] }]}><Icon name={icon || c[2]} size={18} color={c[1]} />
    <Text style={[T.subhead, { color: c[1], flex: 1 }]}>{text}</Text></View>;
  return onPress ? <Pressable onPress={onPress} accessibilityRole="button">{body}</Pressable> : body;
}
// Segmented choice: large targets, selected state also announced to VoiceOver.
export function Seg({ options, value, onChange, small }) {
  const t = useTheme();
  return (
    <View style={{ flexDirection: "row", gap: small ? 4 : 6 }}>
      {options.map(([v, label]) => (
        <Pressable key={v} onPress={() => { tap(); onChange(v); }} accessibilityRole="button" accessibilityLabel={String(label)} accessibilityState={{ selected: value === v }}
          style={[st.seg, { backgroundColor: value === v ? t.tint : t.fill }]}>
          <Text style={[small ? T.subhead : T.subhead, { color: value === v ? t.onTint : t.ink, fontWeight: "600" }]}>{label}</Text>
        </Pressable>))}
    </View>
  );
}
export function Bullets({ items, color }) {
  const t = useTheme();
  return <View style={{ marginTop: 4 }}>{items.map((x, i) => (
    <View key={i} style={{ flexDirection: "row", marginVertical: 3 }}><Text style={[T.body, { color: color || t.ink, width: 18 }]}>•</Text>
      <Text style={[T.body, { color: color || t.ink, flex: 1 }]}>{x}</Text></View>))}</View>;
}
// Minimal markdown for coach messages: headings, bullets, **bold**.
export function MD({ text }) {
  const t = useTheme();
  const inline = (line, key) => line.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <Text key={key + "-" + i} style={{ fontWeight: "700" }}>{part.slice(2, -2)}</Text> : part);
  return <View>{String(text || "").split("\n").map((raw, i) => {
    const line = raw.trimEnd();
    if (!line.trim()) return <View key={i} style={{ height: 6 }} />;
    const h = line.match(/^#{1,4}\s+(.*)/), b = line.match(/^\s*[-*]\s+(.*)/);
    if (h) return <Text key={i} style={[T.headline, { color: t.ink, marginTop: 8 }]}>{inline(h[1], i)}</Text>;
    if (b) return <View key={i} style={{ flexDirection: "row", marginVertical: 2 }}><Text style={[T.body, { color: t.ink, width: 18 }]}>•</Text>
      <Text style={[T.body, { color: t.ink, flex: 1 }]}>{inline(b[1], i)}</Text></View>;
    return <Text key={i} style={[T.body, { color: t.ink }]}>{inline(line, i)}</Text>;
  })}</View>;
}
// Kept for screens that still want a plain container.
export function Card({ children, style, accent }) {
  const t = useTheme();
  return <View style={[{ backgroundColor: t.card, borderRadius: 12, padding: 16, marginBottom: 12 }, accent && { borderLeftWidth: 4, borderLeftColor: accent }, style]}>{children}</View>;
}
export const Kicker = ({ children, color }) => { const t = useTheme(); return <Text style={[T.footnote, { color: color || t.mute, fontWeight: "600", marginBottom: 2 }]}>{children}</Text>; };

const st = StyleSheet.create({
  btn: { borderRadius: 14, paddingVertical: 14, paddingHorizontal: 18, alignItems: "center", justifyContent: "center", minHeight: 50 },
  pill: { alignSelf: "flex-start", paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999 },
  notice: { flexDirection: "row", gap: 10, alignItems: "flex-start", padding: 12, borderRadius: 12, marginBottom: 12 },
  seg: { flex: 1, minHeight: 44, borderRadius: 10, alignItems: "center", justifyContent: "center" },
});
