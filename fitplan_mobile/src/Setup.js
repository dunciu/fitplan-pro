// First launch: point the app at your FitPlan server, then link your account with a pairing code or start fresh.
import React, { useState } from "react";
import { ScrollView, Text, TextInput, View } from "react-native";
import { api, saveConfig } from "./api";
import { Button, Footnote, Group, Header, Notice, Section, T, useTheme } from "./ui";

export default function Setup({ onReady, initialBase }) {
  const t = useTheme();
  const [base, setBase] = useState(initialBase || "");
  const [code, setCode] = useState("");
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState("");
  const input = [T.body, { color: t.ink, paddingHorizontal: 16, paddingVertical: 14, minHeight: 50 }];
  const clean = () => base.trim().replace(/\/+$/, "");

  async function run(kind, fn) {
    setBusy(kind);
    try { await fn(); } catch (e) { setStatus({ ok: false, text: e.message }); } finally { setBusy(""); }
  }
  const test = () => run("test", async () => {
    const h = await api("/health", { base: clean() });
    setStatus({ ok: true, text: h.mock_mode ? "Connected. The server is in demo mode, so plans are placeholders." : "Connected to your FitPlan server." });
  });
  const link = () => run("link", async () => {
    const r = await api("/pair/claim", { method: "POST", body: { code }, base: clean() });
    await saveConfig({ base: clean(), token: r.token });
    onReady();
  });
  const fresh = () => run("fresh", async () => {
    const r = await api("/session", { method: "POST", base: clean() });
    await saveConfig({ base: clean(), token: r.token });
    onReady();
  });

  return (
    <ScrollView contentContainerStyle={{ padding: 16, paddingTop: 28 }} keyboardShouldPersistTaps="handled">
      <Header title="FitPlan" subtitle="Welcome" />
      <Text style={[T.body, { color: t.mute, marginBottom: 8 }]}>A research agent, a critic and an editor build your plan. Then your coach adapts it to how you feel each day.</Text>

      <Section>Your server</Section>
      <Group>
        <TextInput testID="base" style={input} value={base} onChangeText={setBase} autoCapitalize="none" autoCorrect={false} keyboardType="url"
          placeholder="https://….trycloudflare.com or http://192.168.1.10:8000" placeholderTextColor={t.mute} accessibilityLabel="Server address" />
      </Group>
      <Footnote>The address of the computer running FitPlan. On blocked Wi-Fi, use the address from the cloudflared tunnel.</Footnote>
      <Button title="Test connection" kind="secondary" onPress={test} busy={busy === "test"} disabled={!base.trim()} style={{ marginTop: 12 }} testID="test" />
      {status && <View style={{ marginTop: 12 }}><Notice tone={status.ok ? "good" : "bad"} text={status.text} /></View>}

      <Section>Link your account</Section>
      <Group>
        <TextInput testID="code" style={[input, { fontSize: 28, letterSpacing: 8, textAlign: "center", fontWeight: "700" }]} value={code}
          onChangeText={x => setCode(x.toUpperCase())} autoCapitalize="characters" autoCorrect={false} maxLength={8} placeholder="ABC123"
          placeholderTextColor={t.mute} accessibilityLabel="Pairing code" />
      </Group>
      <Footnote>On the web app open Settings, then Your iPhone, then Show a pairing code.</Footnote>
      <Button title="Link this phone" onPress={link} busy={busy === "link"} disabled={code.trim().length < 6 || !base.trim()} style={{ marginTop: 12 }} testID="link" />
      <Button title="Start fresh on this phone" kind="plain" onPress={fresh} busy={busy === "fresh"} disabled={!base.trim()} style={{ marginTop: 4 }} testID="fresh" />
    </ScrollView>
  );
}
