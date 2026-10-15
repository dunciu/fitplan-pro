// TEST-ONLY stand-in for react-native, so the real app code can be compiled with esbuild and driven in a browser.
// It maps components to HTML elements. It does not reproduce native iOS rendering; the phone uses real React Native.
import React, { createContext, useContext, useEffect, useState } from "react";

const UNITLESS = new Set(["flex", "flexGrow", "flexShrink", "opacity", "zIndex", "fontWeight", "lineHeight_", "aspectRatio"]);
export function flatten(style) {
  if (!style) return {};
  if (Array.isArray(style)) return style.reduce((a, s) => Object.assign(a, flatten(s)), {});
  return { ...style };
}
function css(style, base = {}) {
  const s = flatten(style), out = { ...base };
  for (const [k, v] of Object.entries(s)) {
    if (v === undefined || v === null) continue;
    if (k === "paddingHorizontal") { out.paddingLeft = out.paddingRight = v; continue; }
    if (k === "paddingVertical") { out.paddingTop = out.paddingBottom = v; continue; }
    if (k === "marginHorizontal") { out.marginLeft = out.marginRight = v; continue; }
    if (k === "marginVertical") { out.marginTop = out.marginBottom = v; continue; }
    if (k.startsWith("shadow") || k === "elevation" || k === "transform" || k === "tintColor") continue;
    if (k === "borderWidth") { out.borderStyle = out.borderStyle || "solid"; }
    if (/^border(Left|Right|Top|Bottom)Width$/.test(k)) out[k.replace("Width", "Style")] = "solid";
    if (k === "lineHeight" && typeof v === "number") { out.lineHeight = v + "px"; continue; }
    out[k] = typeof v === "number" && !UNITLESS.has(k) ? v + "px" : v;
  }
  if (out.borderWidth && !out.borderColor) out.borderColor = "transparent";
  return out;
}
const VIEW = { display: "flex", flexDirection: "column", position: "relative", boxSizing: "border-box", minWidth: 0, flexShrink: 0 };
const a11y = p => ({ "aria-label": p.accessibilityLabel, "data-testid": p.testID, role: p.accessibilityRole === "button" || p.accessibilityRole === "tab" ? "button" : undefined,
  "aria-selected": p.accessibilityState && p.accessibilityState.selected ? "true" : undefined });

export const StyleSheet = { create: s => s, flatten, hairlineWidth: 1, absoluteFill: { position: "absolute", left: 0, right: 0, top: 0, bottom: 0 } };
export const View = React.forwardRef((p, ref) => <div ref={ref} style={css(p.style, VIEW)} {...a11y(p)}>{p.children}</div>);
const InText = createContext(false);
export function Text(p) {
  const nested = useContext(InText);
  const st = css(p.style, nested ? {} : { display: "block", whiteSpace: "pre-wrap", fontFamily: "-apple-system, system-ui, sans-serif" });
  const El = nested ? "span" : "div";
  return <InText.Provider value={true}><El style={st} {...a11y(p)}>{p.children}</El></InText.Provider>;
}
export function Pressable(p) {
  const [pressed, setPressed] = useState(false);
  const style = typeof p.style === "function" ? p.style({ pressed }) : p.style;
  return <div style={css(style, { ...VIEW, cursor: "pointer" })} {...a11y(p)} role={p.accessibilityRole === "tab" ? "tab" : "button"}
    onMouseDown={() => setPressed(true)} onMouseUp={() => setPressed(false)} onClick={e => { e.stopPropagation(); p.onPress && p.onPress(e); }}>
    {typeof p.children === "function" ? p.children({ pressed }) : p.children}</div>;
}
export const TouchableOpacity = Pressable;
export function ScrollView(p) {
  const outer = css(p.style, { ...VIEW, overflow: "auto", flexGrow: p.horizontal ? 0 : 1, flexShrink: 1, ...(p.horizontal ? { overflowX: "auto" } : {}) });
  const inner = css(p.contentContainerStyle, { ...VIEW, ...(p.horizontal ? { flexDirection: "row" } : {}) });
  return <div style={outer} data-testid={p.testID}>{p.refreshControl}<div style={inner}>{p.children}</div></div>;
}
export function RefreshControl() { return null; }
export function TextInput(p) {
  const props = { value: p.value ?? "", placeholder: p.placeholder, readOnly: p.editable === false, maxLength: p.maxLength, "data-testid": p.testID,
    onChange: e => p.onChangeText && p.onChangeText(e.target.value), style: css(p.style, { boxSizing: "border-box", font: "inherit", width: "100%" }) };
  return p.multiline ? <textarea {...props} /> : <input type={p.secureTextEntry ? "password" : "text"} {...props} />;
}
export function Switch(p) {
  return <input type="checkbox" role="switch" data-testid={p.testID} aria-label={p.accessibilityLabel} checked={!!p.value}
    onChange={e => p.onValueChange && p.onValueChange(e.target.checked)} style={{ width: 44, height: 26 }} />;
}
export function Modal(p) {
  if (!p.visible) return null;
  return <div data-testid="modal" style={{ position: "fixed", inset: 0, zIndex: 50, display: "flex", flexDirection: "column", justifyContent: "flex-end" }}>{p.children}</div>;
}
export function ActivityIndicator() { return <div style={{ textAlign: "center", fontSize: 18 }}>…</div>; }
export const KeyboardAvoidingView = View;
export const Alert = { alert: (title, msg, buttons = []) => {
  const ok = buttons.find(b => b.style !== "cancel");
  if (!buttons.length) return window.alert(title + "\n" + (msg || ""));
  if (window.confirm(title + "\n" + (msg || ""))) ok && ok.onPress && ok.onPress();
} };
export const Linking = { openURL: async url => { window.__opened = url; } };
export const AppState = { currentState: "active", addEventListener: () => ({ remove() {} }) };
export const Platform = { OS: "web", select: o => o.web ?? o.default };
export const Dimensions = { get: () => ({ width: window.innerWidth, height: window.innerHeight }) };
export function useColorScheme() {
  const q = window.matchMedia("(prefers-color-scheme: dark)");
  const [d, setD] = useState(q.matches);
  useEffect(() => { const f = e => setD(e.matches); q.addEventListener("change", f); return () => q.removeEventListener("change", f); }, []);
  return d ? "dark" : "light";
}
class AnimatedValue {
  constructor(v) { this.v = v; } setValue(v) { this.v = v; }
  interpolate() { return 0; }
}
const anim = () => ({ start: cb => cb && cb({ finished: true }) });
export const Animated = {
  Value: AnimatedValue, View: p => <View {...p} style={[flatten(p.style), { opacity: 1, transform: undefined }]} />,
  timing: anim, delay: anim, sequence: () => anim(), parallel: () => anim(),
};
