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
| `rgp_proxy.py` | Local Python proxy bridging the browser to RockGymPro (RGP), When I Work (WIW), and the Claude API. Runs on `127.0.0.1:5001`. |
| `rgp_proxy_config.json` | RGP credentials / facility code loaded by the proxy. |
| `AspireSchedule.html` | Standalone schedule view. |
| `LAUNCH_OperatorOS.bat` | Local launcher (starts the proxy + opens the app). |

## Running locally
Start the proxy, then open `OperatorOS.html` (or use `LAUNCH_OperatorOS.bat`):

```bash
python rgp_proxy.py   # serves on http://127.0.0.1:5001
```

## Notes
- This repo is inside a Dropbox folder. If git ever throws odd index/lock
  errors, it may be a mid-sync conflict — pausing Dropbox during commits/pushes
  resolves it.
- Validate before committing: `python -c "import py_compile; py_compile.compile('rgp_proxy.py', doraise=True)"`
  for the proxy, and extract the `<script>` block and run `node --check` for the
  HTML's JS.
