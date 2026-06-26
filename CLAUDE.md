# OperatorOS — Complete Project Guide

---

## 🔒 LOCKED CODE — DO NOT MODIFY WITHOUT EXPLICIT INSTRUCTION

The following revenue logic is confirmed correct and must not be changed unless Kyle explicitly asks:

### Revenue Calculation (rgp_proxy.py)
- **`/intel/ytd`**: fetches all YTD invoices with `max_pages=100` (44 pages for 2026). Returns `net_revenue` (amount − salesTax), `ytd_tax`, `by_month_net`, `by_month`. Verified against actual RGP figures: net = $601,287.63 vs actual $601,288 (±$0.37 rounding only).
- **`/invoices`**: returns `total_revenue` as net pre-tax (`amount − salesTax`), `total_gross`, `total_tax`, `today_revenue` as net pre-tax.
- **Key insight**: RGP `amount` field includes HST. `salesTax` is the exact tax portion. `amount − salesTax` = pre-tax net sales. Verified via `items[].isTaxItem` cross-check.
- **Page limit**: `fetch_all` default is `max_pages=40` (8,000 invoices). YTD explicitly passes `max_pages=100` to cover all 8,620+ invoices. Do NOT revert this to the default.

### Revenue Display (OperatorOS.html — `loadRevenue()`)
- `monthRev` uses `ytd.by_month_net[curMonth]` (pre-tax monthly figure)
- `ytdRev` uses `ytd.net_revenue` (pre-tax YTD total)
- Fallback chain preserved: `ytd.net_revenue || ytd.ytd_revenue || 0`

### Member Status (rgp_proxy.py — `calc_status()`)
- `currentStatus = 'OK'` from RGP is trusted directly — checked BEFORE expiry date logic
- Monthly-recurring members have no future expiry date; trusting RGP's own status gives correct 704 active count
- Order: TERMINATED → FROZEN → OK → expiry date fallback → visit date fallback → UNKNOWN

---

## What This Is

OperatorOS is a gym intelligence platform built for Aspire Climbing (Milton + Whitby, Ontario). It pulls live data from RockGymPro (RGP) and When I Work (WIW), runs AI analysis via Claude, and gives the operator a single dashboard to manage members, revenue, programs, staff scheduling, and dead time.

It is also designed as a future SaaS product to sell to other climbing gyms (the "Two Sale" strategy — sell the first copy to Aspire, build the dataset, sell the company).

---

## Repository & File Locations

| Location | Purpose |
|----------|---------|
| `E:\IMPACT CLIMBING Dropbox\kyle Wilson\2.0\APP\operatoros-proxy` | **Git repo — single source of truth.** Edit AND launch from here. |
| `E:\IMPACT CLIMBING Dropbox\kyle Wilson\2.0\APP\ASPIRE OS new` | **DEPRECATED copy.** No longer launched. Its `LAUNCH_OperatorOS.bat` now just forwards to the repo launcher. Safe to delete once you're confident. |
| `https://github.com/KYLEW4444/operatoros-proxy.git` | Remote origin |
| Railway project `industrious-upliftment` | Hosted proxy deployment |

### Mandatory Workflow

1. Edit files in `operatoros-proxy/`
2. Launch directly from the repo with `LAUNCH_OperatorOS.bat` (it is self-locating via `%~dp0`, so it always runs the repo's own `OperatorOS.html` + `rgp_proxy.py`). No mirror step — the old `ASPIRE OS new` copy caused stale-launch bugs and is no longer used.
3. Commit/push only when explicitly asked (`railway up` to deploy — `git push` alone does NOT auto-deploy)

---

## Architecture

```
Browser (OperatorOS.html)
    │
    ├── Auto-detects proxy: Railway first → local fallback
    │
    ▼
rgp_proxy.py  [Railway: 0.0.0.0:PORT  /  Local: 127.0.0.1:5001]
    │
    ├── /members          → RGP /v1/customers/facility/{fc}
    ├── /bookings/summary → RGP /v1/bookings/facility/{fc}
    ├── /invoices         → RGP /v1/invoices/facility/{fc}
    ├── /intel/monthly    → RGP (two months of invoices + bookings)
    ├── /checkins/history → RGP /v1/checkins/facility/{fc}
    ├── /checkins/active  → RGP /v1/checkins/active/facility/{fc}
    ├── /checkins/today   → RGP /v1/checkins/facility/{fc} (today)
    ├── /traffic/heatmap  → Fallback: estimates from invoices + bookings timestamps
    ├── /dashboard        → Aggregates members/checkins/revenue in one call
    ├── /discover         → Tests all endpoints for a given facility code
    ├── /wiw/shifts       → When I Work API (login + shift fetch)
    ├── /ai/call          → Anthropic API (POST, proxied, credentials server-side)
    ├── /config/status    → Returns booleans only (never secrets)
    └── /config/set       → Writes credentials to server config (localhost trusted; remote needs ADMIN_TOKEN)
```

### Proxy URL Resolution

`OperatorOS.html` runs `resolveProxy()` at startup: health-checks Railway first, falls back to `http://127.0.0.1:5001`. URL is stored in `S.proxy` and used for all API calls.

Railway deployed URL: `https://operatoros-proxy-production.up.railway.app`

### Concurrency & Sync Robustness

- The proxy uses **`ThreadingHTTPServer`** (not the single-threaded `HTTPServer`). With `protocol_version = 'HTTP/1.1'` (keep-alive), a single-threaded server let each persistent browser connection monopolize the one worker, so the burst of concurrent calls `syncAll()` fires (members, invoices, bookings, check-ins ×2, WIW) serialized and the sync appeared to hang forever. Threading lets each connection run on its own worker. `daemon_threads = True` so the process still exits cleanly.
- **Every client data fetch goes through `pfetch(url, ms)`** (default 25s timeout via `AbortSignal.timeout`). A stuck RGP/WIW call can no longer leave a fetch pending forever, so the Sync spinner always clears.
- **WIW is decoupled from the RGP sync.** `syncWIW()` runs independently in `syncAll()` and does NOT drive the global Sync spinner. Previously it ran only inside the RGP chain's `.finally`, so a slow/hung RGP pull left the WIW dot grey. WIW dot states: grey = not configured, yellow = syncing, green = shifts synced, red = sync failed.
- `setSyncState(false)` runs in the RGP chain's `.finally` unconditionally — the spinner clears regardless of WIW.

---

## Credential & Security Model

- **Secrets never in the browser.** No RGP key, Claude key, or WIW password ever touches `localStorage`.
- Credentials live in `rgp_proxy_config.json` (local) or Railway environment variables (hosted). Env vars take precedence.
- `GET /config/status` → booleans only (`{rgp: true, claude: true, wiw: false}`)
- `POST /config/set` → localhost is trusted; remote requires `X-Admin-Token` header matching `ADMIN_TOKEN` env var
- Rate limit: 240 requests / 60s per IP (in-memory sliding window)
- RGP and WIW: SSL cert verification disabled (avoids Windows/Railway TLS flakiness; Chrome unaffected)
- All Claude calls (chat, actions, intel, social) go through the proxy's `/ai/call` — the browser never holds or sends the Claude key. `CONFIG_STATUS.claude` is the sole availability gate (a boolean from `/config/status`).
- `/config/set` routing: the browser always probes the LOCAL proxy first (file write persists). Railway proxy writes only to process env (lost on container restart) and requires `ADMIN_TOKEN` for remote callers. For permanent Railway credentials, set them via the Railway dashboard env vars (`CLAUDE_KEY`, `WIW_EMAIL`, `WIW_PASSWORD`).

### Railway Environment Variables Required

```
RGP_USER         RGP API username
RGP_KEY          RGP API key
FACILITY_CODE    e.g. ASP (Milton) or ASPW (Whitby)
CLAUDE_KEY       Anthropic API key (optional — enables AI features)
WIW_EMAIL        When I Work login email (optional)
WIW_PASSWORD     When I Work password (optional)
GYM              Display name, e.g. "Aspire Climbing"
LOCATION         e.g. "Milton, Ontario"
ADMIN_TOKEN      Guards POST /config/set on the hosted instance
```

---

## Project Files

| File | Purpose |
|------|---------|
| `OperatorOS.html` | The entire client app — all HTML, CSS, JS in one file. No framework, no build step. |
| `rgp_proxy.py` | Python proxy v3.5. Runs locally or on Railway. All external API calls go through here. **Threaded** (`ThreadingHTTPServer`) so concurrent calls don't serialize. |
| `rgp_proxy_config.json` | **Gitignored.** Local credentials. Copy from `rgp_proxy_config.example.json`. |
| `watch_proxy.py` | File-watcher + supervisor: auto-restarts the proxy when source files change. |
| `WATCH_OperatorOS.bat` | Starts the watcher (dev mode: edit → auto-restart). |
| `LAUNCH_OperatorOS.bat` | Kills old proxy, starts fresh, opens app in browser. Day-to-day launcher. |
| `AspireSchedule.html` | Standalone schedule view (separate from the main app). |
| `Procfile` | Railway process declaration: `web: python rgp_proxy.py` |
| `railway.json` | Railway build config |
| `requirements.txt` | Python deps (stdlib only — intentionally no pip packages) |

---

## What's Built and Working

### Login System
- PIN-based login screen with two user profiles: Kyle (Owner — full access) and Manager
- Staff page requires re-entering the owner PIN even after login (wage data protection)
- PINs stored in proxy config (not localStorage)

### Home Dashboard
- Five zone cards: Fix Now (urgent actions count), At Risk (members), Active Members, Revenue 30d, Social Queue
- Tile grid linking to all modules
- Auto-syncs RGP on load if credentials are set
- Multi-location tile shows "Soon" — not built yet

### RGP Data Integration (fully working)
- **Members:** Full roster up to 500, sorted by last visit. Status calculated: OK / AT_RISK (no visit 30d) / LAPSED (no visit 60d) / FROZEN / EXPIRED / TERMINATED
- **Revenue:** Last 30 days of invoices, voided invoices excluded, newest first
- **Bookings:** Program-level summary (name, bookings count, revenue, cancellations) YTD
- **Check-in history:** 30-day heatmap — hourly distribution + day-of-week breakdown
- **Check-ins active:** Real-time "on floor now" count from `/v1/checkins/active/facility/{fc}`
- **Intelligence / monthly trend:** This month vs last month — revenue %, booking %, cancellation delta
- **Traffic heatmap fallback:** When check-ins API is unavailable, estimates from invoice + booking timestamps

### Programs Page
- Live from RGP bookings summary
- KPIs: total programs, total bookings, total revenue, total cancelled
- Status labels: Growing (>$5K revenue) / Dead (0 bookings) / Monitor

### Staff Module (wages locked behind owner PIN)
- 16 staff hardcoded: Zack, Joshua, Paige, Abbey Lynn, Nick, Jen, Ava K, David, Erin G, Neelya, Maxwell, Tanner, Dax, Brooklyn, Will, Maiya
- Three tiers: T3 (coaches, $17.60–$24/hr), T2 (operators, $16.60–$17.60/hr), T1 (support, $16.60–$17.60/hr)
- Skills tracked: ninja, climb, desk
- Role descriptions and "never do" rules per staff member
- Filter by tier
- Labor Cost tab (owner only): weekly hours + cost by position, by day, labor vs RGP revenue by program

### Schedule Module (fully functional, data stored in localStorage)
- Weekly calendar grid: all staff × 7 days, shift blocks color-coded by position
- Positions: Floor (blue), Desk (green), Coach (purple), Party (amber), Camp (cyan)
- Add/edit/delete shifts, conflict detection
- Copy previous week
- Time off requests: save as pending or approved, approve from list
- Roster view: staff with tier, skills, weekly hours
- Availability page: set per-staff per-day availability windows
- Timesheet: hours only (no wages shown — for manager-level use)
- Auto-Assign: algorithm matches programs to eligible staff by tier + skill + cost-minimizing, flags gaps
- Export: timesheet CSV, schedule CSV, email staff (opens mailto: — see known issues)

### Dead Time Engine
- Heatmap from real RGP check-in data (30 days)
- Three static dead time opportunity items (not dynamically generated from heatmap — see known issues)
- "Generate Promo Post" button triggers Social Auto-Pilot
- **"How This Works" button** (top of page, next to Generate Promo Post) opens a modal with three sections:
  1. Reading the Heatmap — explains visitor count estimates, color thresholds (Red 0–5, Orange 6–20, Green 21–50, Blue 50+), and notes data is estimated until RGP check-in API is connected
  2. Understanding Dead Time Opportunities — explains lowest-traffic windows, staff-cost vs revenue logic, and Draft Post button
  3. How OperatorOS Uses This — explains feed into Actions list + AI Intelligence, how syncs improve recommendations
- Modal CSS classes: `.hiw-overlay`, `.hiw-panel`, `.hiw-section`, `.hiw-legend`, `.hiw-leg`
- JS functions: `openHowItWorks()`, `closeHowItWorks()`

### Members Page
- Filter: All / At Risk / Lapsed
- Table: name, membership type, status pill, last visit, join date, health tag
- Member counts update live on sync

### Revenue Page
- Last 30 days of invoices, paginated to top 100 displayed
- Voided invoices shown with red flag
- KPIs: total revenue, invoice count

### Intelligence Page
- Pulls this-month vs last-month from proxy `/intel/monthly`
- AI analysis of: 3 revenue opportunities, 3 risks, dead time insight, retention insight
- Requires Claude API key in proxy config

### Social Auto-Pilot
- Three post types: Dead Time (fills slow slots), Program Promo (intake campaign), Win-Back (lapsed members)
- AI writes posts via Claude using live gym context
- Draft queue with editable text, platform toggles (IG/FB/TikTok), datetime picker
- "Approve & Schedule" button shows a toast — actual publishing not connected (see next steps)

### AI Chat Sidebar
- Multi-turn conversation with Claude
- System prompt includes live data: member counts, at-risk count, program count, WIW shift count, 30d revenue
- Quick question buttons: "What should I do first today?", "Which members are at risk?", etc.
- Routes through proxy `/ai/call` — same secure path as all other AI calls

### Actions List
- 6 base actions hardcoded (Aspire-specific): League of Nemos oversubscribed, uncovered party slots, H.I.T Bootcamp dead, Kelsos fill rate, camp staffing, Rattlesnakes expansion opportunity
- "AI Refresh" button regenerates from live gym data via Claude
- Action buttons show "coming soon" toast instead of navigating

### Connections Page
- RGP: Test button, Discover button (tests all API endpoints)
- WIW: Test button
- Redpoint: "Coming Q3 2026"
- Mindbody: "Coming Q4 2026"
- Square: "Coming Q4 2026"

### Settings Page
- Gym name, location, proxy URL
- RGP: proxy URL, username, API key, facility codes for Milton (ASP) and Whitby (ASPW), active facility selector
- WIW: email, password
- Claude: API key
- Owner/Manager PINs
- Save POSTs to `/config/set` → stored in proxy config, not localStorage

---

## What's Broken or Incomplete

### Data Issues
- **Dead time opportunities are static**, not derived from the actual heatmap. `renderDeadOpps()` hardcodes three Aspire-specific items regardless of real check-in data.
- **Staff data is hardcoded in JS** (the `STAFF` array). Adding/removing staff requires a code change. No UI to manage it.
- **Schedule data only in localStorage** — cleared if browser data is cleared. No server-side persistence.
- **WIW shifts are fetched but not merged into the internal schedule** — they only show as a count in the KPI bar on the Schedule page.

### UI/Feature Gaps
- **Schedule "Publish & notify"** opens one `mailto:` for the first scheduled staff member only — requires manually repeating for each person. Not a real bulk email.
- **Actions action buttons** (e.g. "View Schedule →", "Cancel →") show a toast saying "coming soon" instead of doing anything.
- **Social publishing not connected** — "Approve & Schedule" shows a toast asking to connect Buffer/Meta API. No actual publishing.
- **Multi-location view** (Milton + Whitby) — tile is locked with "Soon". No cross-facility comparison built.
- **Member detail view** — clicking a member row does nothing. No individual member profile/history.
- **Revenue breakdown** — only shows invoice-level rows. No category breakdown (memberships vs programs vs retail), no charting.
- **Intelligence page** — requires manual "Run Analysis" click; does not auto-run on sync.
- **Auto-Assign** only suggests assignments — "Add shift" buttons work, but shift times default to 09:00–13:00 regardless of actual program times.

---

## What Needs to Be Built Next

**Priority 1 — Dynamic dead time opportunities**
- After heatmap loads from RGP, calculate actual dead windows (slots where average visits ≤ threshold) and render real opportunities, not the hardcoded Aspire list. This is the core "dead time" value prop.

**Priority 2 — Staff management UI**
- Add/edit/delete staff from the Settings or Staff page instead of editing the JS array.
- Expose wage editing in the owner-PIN-locked view.

**Priority 3 — Schedule persistence**
- Persist schedule data to the proxy server (new endpoints: `POST /schedule/save`, `GET /schedule/load`) instead of localStorage only.

**Priority 4 — Multi-location**
- Unlock the Multi-Location tile.
- Facility selector on the home screen or a split-view comparing Milton (ASP) vs Whitby (ASPW) for members, revenue, programs.

**Priority 5 — Social publishing**
- Connect to Meta Graph API or Buffer for real post scheduling.
- The draft queue → approve → schedule flow is already built; it just needs the publish call.

**Priority 6 — WIW ↔ internal schedule sync**
- Option A: Import WIW shifts into the internal schedule calendar on sync.
- Option B: Drop the internal scheduler and use WIW as the source of truth (pull WIW into the display only).

**Priority 7 — Member detail + win-back**
- Clicking a member should open a profile: visit history, membership details, risk score, one-click "generate win-back email" via AI.

**Future (SaaS v2 build)**
- Supabase auth + multi-tenant database (facility isolation)
- React frontend on Vercel (replace the single HTML file)
- Square connector
- Mindbody connector
- Redpoint connector
- Normalization layer (all POS data → standard schema)
- Per-facility onboarding wizard

---

## Separate Project: Options Probability Engine

Not part of OperatorOS. Completely separate product:

- **Backend:** `Downloads/probability-engine-backend-final/` — Node.js/Express on Railway at `https://options-probability-engine-production-04e9.up.railway.app`
- **Frontend:** `Downloads/ope-frontend_1/` — React/Vite on Vercel at `probability-engine-frontend.vercel.app`
- Fetches live stock prices from Finnhub, sends to Claude for 5-pillar options analysis (IV, Flow, Delta, OI, Catalyst)
- 20 analyses/hour rate limit on free tier, 5-min in-memory cache
- Currency selector (20 currencies, hardcoded rates — not live)
- Text-to-speech readout on all analysis sections

---

## Running Locally

```bash
# Day-to-day
LAUNCH_OperatorOS.bat

# While developing (auto-restarts on file save)
WATCH_OperatorOS.bat

# Manual
python rgp_proxy.py   # serves on http://127.0.0.1:5001
```

Then open `OperatorOS.html` in Chrome (file:// works — the proxy sets `Access-Control-Allow-Private-Network: true`).

## Deploying to Railway

```bash
cd "E:\IMPACT CLIMBING Dropbox\kyle Wilson\2.0\APP\operatoros-proxy"
railway up
```

**Note:** `git push` alone does NOT deploy. Must use `railway up` (CLI is linked to `industrious-upliftment`).

**TLS caveat:** Windows `curl` (schannel) fails Railway TLS with `CRYPT_E_NO_REVOCATION_CHECK`. Use `curl --ssl-no-revoke` for CLI testing. Chrome works normally.

## Validation Before Committing

```bash
python -c "import py_compile; py_compile.compile('rgp_proxy.py', doraise=True)"
```

For the HTML's JS block: extract and run `node --check`.

## Git Notes

The repo lives inside Dropbox. If git throws lock errors, pause Dropbox during commits/pushes.

The old RGP key was committed in early git history (before it was gitignored) — rotate that key if it was ever sensitive. Current key is gitignored and safe.

---

## Aspire Climbing Context (for AI-generated content)

- **Milton location:** Climbing + ninja gym, programs include LON (League of Nemos), Rattlesnakes, Buffalos, Kelsos, Vanguards, Evos, Summer Camp, Birthday Parties
- **Whitby location:** Coming online; facility code ASPW
- **Key programs by revenue:** LON Nemos (oversubscribed at 117%), Rattlesnakes (92% fill — needs 3rd session), Kelsos (42% fill — needs marketing), H.I.T Bootcamp (0 pax — cancel)
- **Staff structure:** T3 coaches own programs; T2 operators run parties/desks; T1 support is floor-only
- **Owner:** Kyle Wilson — full access, PIN-protected wage visibility
