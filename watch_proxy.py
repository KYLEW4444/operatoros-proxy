#!/usr/bin/env python3
"""
OperatorOS proxy supervisor + file watcher.

Runs the local proxy and AUTOMATICALLY restarts it whenever rgp_proxy.py or
OperatorOS.html changes in the repo — no need to touch LAUNCH_OperatorOS.bat.

- Changed code files are mirrored from the repo into the launcher folder.
- The proxy config (rgp_proxy_config.json) holds credentials and is NEVER
  mirrored or overwritten.
- If the proxy ever dies on its own, the watcher restarts it.

Run:  python watch_proxy.py        (or double-click WATCH_OperatorOS.bat)
Stop: Ctrl+C (or close the window).
"""
import os, sys, time, subprocess, shutil

REPO       = r'E:\IMPACT CLIMBING Dropbox\kyle Wilson\2.0\APP\operatoros-proxy'
LAUNCHER   = r'E:\IMPACT CLIMBING Dropbox\kyle Wilson\2.0\APP\ASPIRE OS new'
CODE_FILES = ['rgp_proxy.py', 'OperatorOS.html']     # config is intentionally excluded
PORT       = os.environ.get('PORT', '5001')


def mtimes():
    out = {}
    for f in CODE_FILES:
        try:    out[f] = os.path.getmtime(os.path.join(REPO, f))
        except OSError: out[f] = 0
    return out


def mirror():
    """Copy code files repo -> launcher (never the credentials config)."""
    for f in CODE_FILES:
        src, dst = os.path.join(REPO, f), os.path.join(LAUNCHER, f)
        if os.path.exists(src):
            try:    shutil.copy2(src, dst)
            except Exception as e: print(f'  [watch] mirror {f} failed: {e}')


def start_proxy():
    mirror()
    env = dict(os.environ)
    env['PYTHONIOENCODING'] = 'utf-8'   # avoid cp1252 crashes on the status logging
    env['PORT'] = PORT
    print(f'[watch] starting proxy on http://127.0.0.1:{PORT} ...')
    return subprocess.Popen([sys.executable, os.path.join(LAUNCHER, 'rgp_proxy.py')],
                            cwd=LAUNCHER, env=env)


def stop_proxy(proc):
    if proc and proc.poll() is None:
        print('[watch] stopping proxy ...')
        try:
            proc.terminate()
            try:    proc.wait(timeout=5)
            except subprocess.TimeoutExpired: proc.kill()
        except Exception:
            pass


def main():
    print('OperatorOS proxy watcher — auto-restarts the proxy when code changes.')
    print('Watching:', ', '.join(CODE_FILES))
    print('Press Ctrl+C (or close this window) to stop.\n')
    proc = start_proxy()
    last = mtimes()
    try:
        while True:
            time.sleep(1.0)
            if proc.poll() is not None:          # proxy died — bring it back
                print('[watch] proxy exited unexpectedly — restarting.')
                proc = start_proxy(); last = mtimes(); continue
            cur = mtimes()
            changed = [f for f in CODE_FILES if cur[f] != last[f]]
            if changed:
                print(f'[watch] change detected: {", ".join(changed)} — restarting with fresh code.')
                stop_proxy(proc)
                time.sleep(1.0)                  # let the port release
                proc = start_proxy()
                last = cur
    except KeyboardInterrupt:
        print('\n[watch] shutting down.')
    finally:
        stop_proxy(proc)


if __name__ == '__main__':
    main()
