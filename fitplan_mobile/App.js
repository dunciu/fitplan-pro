// FitPlan for iPhone (Expo Go). Talks to your FitPlan server; data arrives live from Google Health / WHOOP / Apple Health
// on the server, and this app refreshes every minute while open, whenever you come back to it, and on pull-to-refresh.
import React, { useCallback, useEffect, useRef, useState } from "react";
import { ActivityIndicator, Animated, AppState, Pressable, RefreshControl, ScrollView, StyleSheet, Text, View, useColorScheme } from "react-native";
import { SafeAreaProvider, SafeAreaView, useSafeAreaInsets } from "react-native-safe-area-context";
import { StatusBar } from "expo-status-bar";
import { ApiError, api, loadConfig, saveConfig, today } from "./src/api";
import { Button, Header, Icon, Notice, P, T, Theme, tap, themeFor } from "./src/ui";
import Setup from "./src/Setup";
import Onboard from "./src/Onboard";
import Today from "./src/Today";
import Plan from "./src/Plan";
import Progress from "./src/Progress";
import Coach from "./src/Coach";
import Settings from "./src/Settings";

// Four top-level sections; filled icon when selected (HIG). Settings is a screen, opened from the gear.
const TABS = [["today", "Today", "today"], ["plan", "Plan", "calendar"], ["trends", "Progress", "pulse"], ["coach", "Coach", "chatbubbles"]];
const LIVE_MS = 60_000;

async function fetchTab(tab) {
  const d = today();
  if (tab === "today") { const [day, trends, plan] = await Promise.all([api(`/today?date=${d}`), api(`/trends?days=28&date=${d}`), api("/plan")]); return { day, trends, plan }; }
  if (tab === "plan") return api("/plan");
  if (tab === "trends") return api(`/trends?days=28&date=${d}`);
  if (tab === "coach") {
    const [trends, c, a] = await Promise.all([api(`/trends?days=28&date=${d}`), api("/checkins"), api("/actions")]);
    api("/checkins/seen", { method: "POST" }).catch(() => {});
    return { trends, checkins: c.items, actions: a.items };
  }
  if (tab === "settings") return api("/sync/info");
}

function Main() {
  const scheme = useColorScheme();
  const t = themeFor(scheme);
  const [phase, setPhase] = useState("loading");   // loading | setup | onboard | hold | app
  const [base, setBase] = useState("");
  const [me, setMe] = useState(null);
  const [tab, setTab] = useState("today");
  const [data, setData] = useState({});
  const [err, setErr] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [toastMsg, setToastMsg] = useState("");
  const toastAnim = useRef(new Animated.Value(0)).current;
  const insets = useSafeAreaInsets();
  const tabRef = useRef(tab);
  tabRef.current = tab;

  const toast = useCallback(m => {
    setToastMsg(m);
    Animated.sequence([Animated.timing(toastAnim, { toValue: 1, duration: 180, useNativeDriver: true }), Animated.delay(2200),
      Animated.timing(toastAnim, { toValue: 0, duration: 220, useNativeDriver: true })]).start();
  }, [toastAnim]);

  const reload = useCallback(async (which) => {
    const tb = which || tabRef.current;
    try {
      const m = await api("/me");
      setMe(m);
      if (!m.plan) { setPhase(m.safety && m.safety.level === "hold" ? "hold" : "onboard"); return; }
      setPhase("app");
      setData(old => ({ ...old, [tb]: undefined }));
      const v = await fetchTab(tb);
      setData(old => ({ ...old, [tb]: v }));
      setErr("");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) { await saveConfig({ token: "" }); setPhase("setup"); return; }
      setErr(e.message);
    }
  }, []);

  useEffect(() => { (async () => {
    const c = await loadConfig();
    setBase(c.base);
    if (!c.base || !c.token) return setPhase("setup");
    reload("today");
  })(); }, [reload]);

  // Live: refresh while open, when the app comes back to the foreground, and quickly while the agents are still reviewing.
  useEffect(() => {
    if (phase !== "app") return;
    const id = setInterval(() => reload(), me && me.reviewing ? 5000 : LIVE_MS);
    const sub = AppState.addEventListener("change", s => { if (s === "active") reload(); });
    return () => { clearInterval(id); sub.remove(); };
  }, [phase, me && me.reviewing, reload]);

  const go = tb => { setTab(tb); reload(tb); };
  const onRefresh = async () => { setRefreshing(true); await reload(); setRefreshing(false); };
  const screenProps = { data: data[tab], me: me || {}, reload: () => reload(), toast, setTab: go, setMe };

  let body;
  if (phase === "loading") body = <View style={st.center}><ActivityIndicator color={t.tint} size="large" /></View>;
  else if (phase === "setup") body = <Setup initialBase={base} onReady={async () => { const c = await loadConfig(); setBase(c.base); reload("today"); }} />;
  else if (phase === "onboard") body = <Onboard initial={me && me.profile} onDone={(hold, early) => { if (early) setMe(m => ({ ...m, reviewing: true })); reload("today"); }} />;
  else if (phase === "hold") body = (
    <ScrollView contentContainerStyle={{ padding: 16, paddingTop: 24 }}>
      <Header title="Let's get you checked first" />
      <Notice tone="bad" text={me.safety.message || "A professional should look at this before you start."} />
      <P mute>Once you've been cleared, come back and start again.</P>
      <Button title="Start again" onPress={() => setPhase("onboard")} style={{ marginTop: 14 }} />
    </ScrollView>);
  else {
    const Screen = { today: Today, plan: Plan, trends: Progress, coach: Coach, settings: Settings }[tab];
    body = (
      <View style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={{ padding: 16, paddingTop: 8, paddingBottom: 96 + insets.bottom }} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={t.tint} />}
          keyboardShouldPersistTaps="handled">
          <View style={st.topRow}>
            <View style={{ flex: 1 }} />
            <Pressable onPress={() => { tap(); go(tab === "settings" ? "today" : "settings"); }} accessibilityRole="button"
              accessibilityLabel={tab === "settings" ? "Close settings" : "Settings"} testID="settings" hitSlop={8} style={[st.gear, { backgroundColor: t.card }]}>
              <Icon name={tab === "settings" ? "close" : "settings-outline"} size={22} color={t.ink} /></Pressable>
          </View>
          {!!err && <Notice tone="bad" text={err} onPress={() => reload()} />}
          {data[tab] === undefined && !err ? <ActivityIndicator color={t.tint} style={{ marginTop: 60 }} /> :
            <Screen {...screenProps} onUnlink={async () => { await saveConfig({ token: "" }); setPhase("setup"); }} onNewPlan={() => setPhase("onboard")} />}
        </ScrollView>
        <View style={[st.tabbar, { backgroundColor: t.card, borderTopColor: t.line, paddingBottom: Math.max(insets.bottom, 8) }]}>
          {TABS.map(([k, label, icon]) => {
            const on = tab === k;
            return (
              <Pressable key={k} onPress={() => { if (!on) tap(); go(k); }} accessibilityRole="tab" accessibilityLabel={label} accessibilityState={{ selected: on }}
                testID={"tab-" + k} style={st.tab}>
                <Icon name={on ? icon : icon + "-outline"} size={25} color={on ? t.tint : t.mute} />
                <Text style={[T.caption, { fontWeight: "600", color: on ? t.tint : t.mute }]}>{label}</Text>
                {k === "coach" && me && me.unseen > 0 && <View style={[st.badge, { backgroundColor: t.red }]} />}
              </Pressable>);
          })}
        </View>
      </View>);
  }

  return (
    <Theme.Provider value={t}>
      <SafeAreaView style={{ flex: 1, backgroundColor: t.bg }} edges={["top", "left", "right"]}>
        <StatusBar style={scheme === "dark" ? "light" : "dark"} />
        {body}
        <Animated.View pointerEvents="none" style={[st.toast, { bottom: 84 + insets.bottom, backgroundColor: t.ink, opacity: toastAnim,
          transform: [{ translateY: toastAnim.interpolate({ inputRange: [0, 1], outputRange: [20, 0] }) }] }]}>
          <Text style={[T.subhead, { color: t.bg }]}>{toastMsg}</Text>
        </Animated.View>
      </SafeAreaView>
    </Theme.Provider>
  );
}

export default function App() {
  return <SafeAreaProvider><Main /></SafeAreaProvider>;
}

const st = StyleSheet.create({
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  topRow: { flexDirection: "row", height: 44, marginBottom: -44, zIndex: 2 },
  gear: { width: 44, height: 44, borderRadius: 22, alignItems: "center", justifyContent: "center" },
  tabbar: { position: "absolute", left: 0, right: 0, bottom: 0, flexDirection: "row", borderTopWidth: StyleSheet.hairlineWidth || 1, paddingTop: 6 },
  tab: { flex: 1, alignItems: "center", gap: 2, minHeight: 49, justifyContent: "center" },
  badge: { position: "absolute", top: 4, right: "32%", width: 10, height: 10, borderRadius: 5 },
  toast: { position: "absolute", alignSelf: "center", paddingHorizontal: 16, paddingVertical: 10, borderRadius: 14, maxWidth: "90%" },
});
