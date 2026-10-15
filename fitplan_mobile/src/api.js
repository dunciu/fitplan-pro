// Talks to the FitPlan server (/api/v2). The server address and account token live in the phone's secure storage.
import * as SecureStore from "expo-secure-store";

let BASE = "", TOKEN = "";

export async function loadConfig() {
  BASE = (await SecureStore.getItemAsync("fp_base")) || "";
  TOKEN = (await SecureStore.getItemAsync("fp_token")) || "";
  return { base: BASE, token: TOKEN };
}
export async function saveConfig({ base, token }) {
  if (base !== undefined) { BASE = base.replace(/\/+$/, ""); await SecureStore.setItemAsync("fp_base", BASE); }
  if (token !== undefined) { TOKEN = token; token ? await SecureStore.setItemAsync("fp_token", token) : await SecureStore.deleteItemAsync("fp_token"); }
}
export const getBase = () => BASE;

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

export async function api(path, { method = "GET", body, base } = {}) {
  const url = (base || BASE) + "/api/v2" + path;
  let r;
  try {
    r = await fetch(url, {
      method,
      headers: { "X-User-Token": TOKEN, ...(body ? { "Content-Type": "application/json" } : {}) },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    throw new ApiError("Can't reach the server. Is it running, and is your phone on the same Wi-Fi?", 0);
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(data.error || `Something went wrong (${r.status})`, r.status);
  return data;
}

export const pad = n => String(n).padStart(2, "0");
export const iso = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
export const today = () => iso(new Date());
