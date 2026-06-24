# OperatorOS — Project Guide

## Repository location
This git repo lives at:

```
E:\IMPACT CLIMBING Dropbox\kyle Wilson\2.0\APP\operatoros-proxy
```

It tracks `origin/main` → https://github.com/KYLEW4444/operatoros-proxy.git

(It was moved here from `C:\Users\kyle\OneDrive\Documents\GitHub\operatoros-proxy`,
which no longer exists. Full git history was preserved.)

## ⚠️ Mandatory workflow: edit here, then mirror

**All code changes are made in this repo (`...\APP\operatoros-proxy`).**

**After every change, copy the changed file(s) to the local launcher folder:**

```
E:\IMPACT CLIMBING Dropbox\kyle Wilson\2.0\APP\ASPIRE OS new
```

The `ASPIRE OS new` folder is the **local launcher copy** (run via
`LAUNCH_OperatorOS.bat`). It is NOT a git repo — it is a plain mirror of the
runnable files so the app can be launched locally without touching git.

### How to mirror (run after editing)
Copy whichever files you changed. The two primary files are `OperatorOS.html`
(the single-page app) and `rgp_proxy.py` (the local Python proxy):

```bash
cp "E:/IMPACT CLIMBING Dropbox/kyle Wilson/2.0/APP/operatoros-proxy/OperatorOS.html" \
   "E:/IMPACT CLIMBING Dropbox/kyle Wilson/2.0/APP/ASPIRE OS new/OperatorOS.html"
cp "E:/IMPACT CLIMBING Dropbox/kyle Wilson/2.0/APP/operatoros-proxy/rgp_proxy.py" \
   "E:/IMPACT CLIMBING Dropbox/kyle Wilson/2.0/APP/ASPIRE OS new/rgp_proxy.py"
```

If you change any other file that the launcher needs (e.g. `AspireSchedule.html`,
`LAUNCH_OperatorOS.bat`, `rgp_proxy_config.json`), mirror that one too.

**Do not edit files directly in `ASPIRE OS new`** — it is overwritten by the
mirror step and any edits there would be lost. Edit in the repo, then copy.

### Checklist for any code change
1. Edit the file(s) in `...\APP\operatoros-proxy`.
2. Copy the changed file(s) to `...\APP\ASPIRE OS new` (commands above).
3. Commit/push only when the user asks.

## Project layout
| File | Purpose |
|------|---------|
| `OperatorOS.html` | Single-page app (UI + all client JS). |
| `rgp_proxy.py` | Local Python proxy bridging the browser to RockGymPro (RGP), When I Work (WIW), and the Claude API. Binds `127.0.0.1:5001` only. Per-IP rate limited. |
| `rgp_proxy_config.json` | **All credentials** (RGP, Claude, WIW) + facility code. **Gitignored** — never commit it. Copy `rgp_proxy_config.example.json` to create it. |
| `watch_proxy.py` | Supervisor/file-watcher: runs the proxy and auto-restarts it when `rgp_proxy.py` / `OperatorOS.html` change (mirrors code repo→launcher; never the config). |
| `WATCH_OperatorOS.bat` | Starts the watcher (dev: edit → auto-restart). |
| `LAUNCH_OperatorOS.bat` | One-shot launcher: kills any old proxy (by cmdline + port, waits for the port to free), starts fresh, opens the app. |
| `AspireSchedule.html` | Standalone schedule view. |

## Security model (important)
- **Secrets never live in the browser.** RGP creds, the Claude API key, and WIW
  creds are stored only in `rgp_proxy_config.json`. The frontend sends NO secrets
  on API calls and persists NO secrets in localStorage. It only learns *whether*
  creds are configured via `GET /config/status` (booleans).
- The Settings "Save" button POSTs secrets once to `POST /config/set`
  (localhost-only) which writes them to the config file. On first load after the
  hardening, any legacy secrets still in localStorage are auto-migrated to the
  config and stripped from the browser.
- The proxy binds `127.0.0.1` only and rate-limits each IP
  (`RATE_LIMIT_MAX`/`RATE_LIMIT_WINDOW`).
- `rgp_proxy_config.json` is gitignored. NOTE: it was tracked previously, so the
  old RGP key exists in git history — rotate that key if it was ever sensitive.

## Running locally
Two options:
- **`LAUNCH_OperatorOS.bat`** — kills any old proxy and starts fresh, then opens the app. Use for normal day-to-day.
- **`WATCH_OperatorOS.bat`** — runs the watcher so the proxy auto-restarts on every code change. Use while developing.

Or manually:
```bash
python rgp_proxy.py   # serves on http://127.0.0.1:5001 (localhost only)
```

## Notes
- This repo is inside a Dropbox folder. If git ever throws odd index/lock
  errors, it may be a mid-sync conflict — pausing Dropbox during commits/pushes
  resolves it.
- Validate before committing: `python -c "import py_compile; py_compile.compile('rgp_proxy.py', doraise=True)"`
  for the proxy, and extract the `<script>` block and run `node --check` for the
  HTML's JS.
