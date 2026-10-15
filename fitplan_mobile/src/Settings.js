// Settings: native grouped list. Live sync first, because it's what makes the coach useful.
import React, { useState } from "react";
import { Alert, Linking, Text, View } from "react-native";
import { api, getBase } from "./api";
import { Button, Footnote, Group, Header, Notice, Pill, Row, Section, T, tap, useTheme } from "./ui";

const ago = x => (x ? new Date(x).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "never");
const PROVIDER = { google: ["Fitbit Air and Google Health", "logo-google", "#2453B3", "Sign in with the Google account your Fitbit uses. Your coach sees each night's sleep, resting heart rate and HRV."],
  whoop: ["WHOOP", "fitness", "#5B5F66", "Sign in once and your coach sees each morning's recovery."] };

function Provider({ k, c, minutes, reload, toast }) {
  const t = useTheme();
  const [busy, setBusy] = useState("");
  const [name, icon, color, blurb] = PROVIDER[k];
  async function connect() {
    setBusy("on");
    try { const r = await api(`/connect/${k}/start`, { method: "POST" }); await Linking.openURL(r.url); toast("Finish signing in, then come back here."); }
    catch (e) { toast(e.message); } finally { setBusy(""); }
  }
  async function syncNow() {
    setBusy("sync");
    try { const r = await api(`/connect/${k}/sync`, { method: "POST" }); tap("success"); toast(`Synced ${r.imported_days} days`); await reload(); }
    catch (e) { toast(e.message); } finally { setBusy(""); }
  }
  return (
    <Group style={{ marginBottom: 12 }}>
      <Row icon={icon} iconBg={color} title={name} right={<Pill text={c.connected ? "Connected" : "Off"} tone={c.connected ? "green" : undefined} />}
        subtitle={c.connected ? `Syncs every ${minutes} minutes. Last sync ${ago(c.last_sync)}.` : c.configured ? blurb : "Not set up on the server yet. See the setup guide."} />
      {c.connected ? <>
        <Row title="Sync now" onPress={syncNow} value={busy === "sync" ? "Syncing…" : ""} testID={"sync-" + k} />
        <Row title="Disconnect" onPress={async () => { await api(`/connect/${k}/disconnect`, { method: "POST" }); reload(); }} />
      </> : c.configured ? <View style={{ padding: 16, paddingTop: 4 }}><Button title={`Connect ${c.name}`} onPress={connect} busy={busy === "on"} testID={"connect-" + k} /></View> : null}
    </Group>
  );
}

export default function Settings({ data, me, reload, toast, onUnlink, onNewPlan }) {
  const t = useTheme();
  const [seeding, setSeeding] = useState("");
  if (!data) return null;
  const s = data;
  async function seed(sc) {
    setSeeding(sc);
    try { await api("/demo/seed", { method: "POST", body: { scenario: sc } }); tap("success"); toast("Demo data added. Check Progress and Coach."); await reload(); }
    catch (e) { toast(e.message); } finally { setSeeding(""); }
  }
  const confirm = (title, msg, fn) => Alert.alert(title, msg, [{ text: "Cancel", style: "cancel" }, { text: "OK", style: "destructive", onPress: fn }]);
  return (
    <View>
      <Header title="Settings" subtitle={me.profile ? me.profile.goal : ""} />
      {me.mock_mode && <Notice text="Demo mode: the server has no AI key, so plans are placeholders." />}
      <Section>Live sync</Section>
      <Provider k="google" c={s.connections.google} minutes={s.sync_minutes} reload={reload} toast={toast} />
      <Provider k="whoop" c={s.connections.whoop} minutes={s.sync_minutes} reload={reload} toast={toast} />
      <Group>
        <Row icon="heart" iconBg="#C02B2B" title="Apple Watch and Apple Health" subtitle={`Send data with the Health Auto Export app. Last data received ${ago(s.last_push)}.`} />
        <View style={{ paddingHorizontal: 16, paddingBottom: 14 }}>
          <Text style={[T.footnote, { color: t.mute, marginBottom: 4 }]}>In Health Auto Export: Automations, REST API. Use this URL and header.</Text>
          <Text selectable style={[T.footnote, { color: t.ink, fontFamily: "Menlo" }]}>{s.push_url}</Text>
          <Text selectable style={[T.footnote, { color: t.ink, fontFamily: "Menlo", marginTop: 4 }]}>{"Authorization: Bearer " + s.push_key}</Text>
        </View>
      </Group>
      <Footnote>Press and hold to copy. Keep the key private.</Footnote>

      {me.demo_enabled && <><Section>Try it with sample data</Section>
        <Group>{[["steady", "Steady and recovered", "happy"], ["overreaching", "Overreaching, HRV falling", "trending-down"], ["poor_sleep", "Two weeks of poor sleep", "moon"],
          ["illness", "Signs of getting ill", "thermometer"]].map(([k, n, ic]) => (
          <Row key={k} icon={ic} iconBg={t.blue} title={n} onPress={() => seed(k)} value={seeding === k ? "Adding…" : ""} testID={"seed-" + k} chevron />))}</Group>
        <Footnote>Fills the last four weeks so you can watch the coach react.</Footnote></>}

      <Section>Plan and account</Section>
      <Group>
        <Row icon="add-circle" title="Create a different plan" onPress={() => confirm("Create a new plan?", "Your current plan stays in history but the new one replaces it.", onNewPlan)} chevron />
        <Row icon="server" iconBg="#5B5F66" title="Server" subtitle={getBase()} />
        <Row icon="log-out" iconBg="#C02B2B" title="Unlink this phone" onPress={() => confirm("Unlink this phone?", "Your plan and data stay on the server. You can link again with a pairing code.", onUnlink)} />
      </Group>
      <Footnote>FitPlan gives coaching guidance, not medical advice.</Footnote>
    </View>
  );
}
