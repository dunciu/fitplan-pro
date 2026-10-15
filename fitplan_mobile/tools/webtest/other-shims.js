// TEST-ONLY stand-ins for the Expo modules used by the app.
import React from "react";
import { View } from "react-native";

// expo-secure-store -> localStorage
export const getItemAsync = async k => localStorage.getItem(k);
export const setItemAsync = async (k, v) => localStorage.setItem(k, v);
export const deleteItemAsync = async k => localStorage.removeItem(k);
// expo-status-bar
export const StatusBar = () => null;
// react-native-safe-area-context
export const SafeAreaProvider = ({ children }) => <>{children}</>;
export const SafeAreaView = p => <View {...p} style={[{ minHeight: "100vh", display: "flex" }, p.style]} />;
export const useSafeAreaInsets = () => ({ top: 0, bottom: 0, left: 0, right: 0 });

// @expo/vector-icons -> a small glyph so screenshots stay readable (the phone uses real Ionicons)
const GLYPH = { today: "◉", calendar: "▦", pulse: "∿", chatbubbles: "✉", "settings-outline": "⚙", close: "✕", walk: "🚶", flash: "⚡", map: "⛰", barbell: "🏋",
  bicycle: "🚲", tennisball: "🎾", body: "🧘", moon: "☾", sparkles: "✦", "checkmark-circle": "✓", checkmark: "✓", "chevron-forward": "›", "chevron-down": "⌄",
  "chevron-up": "⌃", create: "✎", happy: "☺", "remove-circle": "–", bandage: "✚", "battery-dead": "▭", "shield-checkmark": "✓", "thumbs-up": "👍",
  "thumbs-down": "👎", book: "☰", heart: "♥", "logo-google": "G", fitness: "W", "add-circle": "+", server: "≡", "log-out": "⇥", "trending-down": "↘",
  thermometer: "🌡", refresh: "↻", trophy: "★", "alert-circle": "!", medkit: "✚", sync: "↻", "ellipse-outline": "○", speedometer: "◔", medal: "🏅", water: "💧" };
export const Ionicons = ({ name, size = 20, color, style }) => {
  const base = String(name).replace(/-outline$/, "");
  const g = GLYPH[name] || GLYPH[base] || "•";
  return <span aria-hidden="true" style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: size, height: size,
    fontSize: size * 0.8, lineHeight: 1, color, fontFamily: "system-ui", ...(style || {}) }}>{g}</span>;
};
// expo-haptics -> no-op
export const impactAsync = async () => {};
export const notificationAsync = async () => {};
export const ImpactFeedbackStyle = { Light: "light", Medium: "medium" };
export const NotificationFeedbackType = { Success: "success" };
