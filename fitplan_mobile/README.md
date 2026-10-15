# FitPlan for iPhone (Expo Go demo)

A React Native app (Expo SDK 57) for the FitPlan server: Today, Plan, Progress, Coach and Settings, with the autopilot,
undo, check-ins and live data from Fitbit Air (Google Health), WHOOP or Apple Health.

It runs in **Expo Go**, so there is no Xcode or App Store step. It only uses modules that ship inside Expo Go.

## 1. Start the server so your phone can reach it (Windows PowerShell)

```powershell
cd C:\Users\uaeor\Downloads\fitplan_app\fitplan_app
.venv\Scripts\Activate.ps1          # or the venv one folder up
$env:ANTHROPIC_API_KEY="sk-ant-..."
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Find your PC's address with `ipconfig` (the IPv4 address, e.g. `192.168.1.23`). Allow Python through the Windows
firewall when asked. Your phone and PC must be on the same Wi-Fi.

## 2. Run the app on your iPhone

1. Install **Node.js 20 or newer** on the PC, and **Expo Go** from the App Store on the iPhone.
2. In a second PowerShell window:
   ```powershell
   cd C:\path\to\fitplan_mobile
   npm install
   npx expo install @expo/vector-icons expo-haptics   # icons and haptic taps (both included in Expo Go)
   npx expo install --fix      # pins every package to the versions SDK 57 expects
   npx expo start
   ```
3. Scan the QR code with the iPhone Camera. It opens in Expo Go.
   If it won't connect (some university or office Wi-Fi blocks this), use `npx expo start --tunnel`.
   Expo Go only runs the newest SDK. If it says the project is incompatible, update Expo Go.

## 3. Link the phone to your account

1. On the PC open `http://localhost:8000` → Settings (gear) → Your iPhone → **Show a pairing code**.
2. In the app enter `http://<your PC IP>:8000`, tap **Test connection**, type the code and tap **Link this phone**.

## Design

- **The app wears today's session.** Today opens with a block in the session's colour: green easy, orange hard, blue long,
  purple strength, teal cross-training, pink skill, grey rest. The minutes are the one big thing on the screen.
- **Everything else is native and quiet:** iOS grouped backgrounds, inset grouped lists like Settings and Health, the
  system font (so the iPhone's text-size setting works), 17 pt body text, sentence-case labels, filled tab icons when
  selected, 44 pt minimum touch targets, haptic taps.
- **One-tap check-in:** Fresh, Normal, Sore or Wrecked. Sleep, heart rate and HRV are optional in a native sheet,
  and synced trackers fill them in.
- **Plain words:** "Recovery week" instead of "deload", day names instead of dates.
- **Contrast:** every colour pair meets WCAG AA (4.5:1). White on the session colours is 5.2 to 7.3:1.

## How "live" works

```
Fitbit Air ──Bluetooth──> Google Health app ──> Google cloud ──(every 60 min)──> FitPlan server ──> autopilot
                                                                                       │
iPhone app <──── refreshes every minute while open, when you come back to it, and on pull-down
```

- The server pulls Google Health and WHOOP every `FITPLAN_SYNC_MINUTES` (default 60, minimum 15).
- After each sync the autopilot checks today, so a short night or an HRV drop can ease today's session before you
  open the app.
- The app shows it the next time it refreshes.

## Connect Fitbit Air (Google Health API)

The Fitbit Air syncs to the **Google Health app**, and its data is read through the **Google Health API**. The old
Fitbit Web API loses support on 30 Sep 2026 and is turned off on 30 Oct 2026, so FitPlan doesn't use it.

1. In the Google Cloud console create a project and **enable the Google Health API**.
2. **OAuth consent screen**: External, keep it in *Testing*, add your own Google account as a test user, and add these
   scopes:
   - `https://www.googleapis.com/auth/googlehealth.sleep.readonly`
   - `https://www.googleapis.com/auth/googlehealth.health_metrics_and_measurements.readonly`
   - `https://www.googleapis.com/auth/googlehealth.activity_and_fitness.readonly`
3. **Credentials → Create OAuth client ID → Web application**. Add this authorised redirect URI:
   `http://localhost:8000/api/v2/connect/google/callback`
4. Before starting the server:
   ```powershell
   $env:GOOGLE_CLIENT_ID="...apps.googleusercontent.com"
   $env:GOOGLE_CLIENT_SECRET="..."
   $env:GOOGLE_REDIRECT_URI="http://localhost:8000/api/v2/connect/google/callback"
   ```
5. On the **PC** open `http://localhost:8000` → Settings → **Connect Google Health** and sign in. The phone shares
   the account, so it sees the data straight away.
   Google only accepts `localhost` or HTTPS redirect addresses. To connect from the phone itself, put the server
   behind an HTTPS tunnel (e.g. `cloudflared tunnel --url http://localhost:8000`). Use that https address in the app
   and as the redirect URI.

**Not yet verified**: the connector follows Google's published docs, but I couldn't test it against a real Google
account. If a value is missing after your first sync, send me one raw response (Settings → Sync now, then the server
log) and the field mapping can be adjusted. Health scopes may need Google's verification before people outside your
test-user list can connect.

## Limits of the Expo Go demo

- Expo Go can't read Apple Health directly. That needs a development build with a HealthKit module. Apple Watch data
  comes in through Health Auto Export instead (Settings shows the URL and key).
- No push notifications yet; the app refreshes when open.

## How it was tested

`tools/webtest/` compiles the real app code with esbuild and runs it in Chromium at iPhone size through a test-only
React Native stand-in, against the server in demo mode. It covers setup, pairing, check-in → autopilot → undo, plan,
Google sign-in link, demo data, progress, coach and a fresh-phone onboarding. It checks the logic and every API call,
but not native iOS rendering. Only running it in Expo Go shows that.
