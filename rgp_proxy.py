"""
OperatorOS RGP Proxy v3.2 — WIW proxy added (cache-bust build)
Credentials load from rgp_proxy_config.json automatically.
Just run this file — no setup needed.
"""
import json, urllib.request, urllib.parse, base64, os, datetime, ssl, re, time, threading
from http.server import HTTPServer, BaseHTTPRequestHandler

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rgp_proxy_config.json')

# config-key  ->  environment-variable name. On Railway (and any hosted deploy)
# credentials come from environment variables; locally they come from the
# config file. Env vars take precedence over the file.
ENV_MAP = {
    'rgp_user':      'RGP_USER',
    'rgp_key':       'RGP_KEY',
    'facility_code': 'FACILITY_CODE',
    'claude_key':    'CLAUDE_KEY',
    'wiw_email':     'WIW_EMAIL',
    'wiw_password':  'WIW_PASSWORD',
    'gym':           'GYM',
    'location':      'LOCATION',
}

def load_config():
    """Merge credentials from the local file (if any) and environment variables.
    Environment variables win, so a hosted deploy (Railway) is driven entirely by
    its env vars while local dev uses the file."""
    cfg = {}
    try:
        with open(CONFIG_FILE, 'r') as f:
            cfg.update(json.load(f) or {})
    except Exception:
        pass
    for ck, ev in ENV_MAP.items():
        val = os.environ.get(ev)
        if val not in (None, ''):
            cfg[ck] = val
    return cfg

def save_config(cfg):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(cfg, f, indent=2)

def is_hosted():
    """True when running on Railway (or another PaaS) rather than locally."""
    return bool(os.environ.get('RAILWAY_ENVIRONMENT') or os.environ.get('RAILWAY_PROJECT_ID')
                or os.environ.get('RAILWAY_SERVICE_ID') or os.environ.get('RAILWAY_STATIC_URL'))

# ── Rate limiting ──────────────────────────────────────────────────────────
# Simple in-memory sliding window per client IP so no single caller can hammer
# the proxy. Generous enough for normal polling (a few requests/min) but blocks
# runaway loops / abuse.
RATE_LIMIT_MAX    = 240   # max requests ...
RATE_LIMIT_WINDOW = 60    # ... per this many seconds, per IP
_rate_lock = threading.Lock()
_rate_hits = {}           # ip -> list[timestamps]

def rate_limited(ip):
    now = time.time()
    with _rate_lock:
        hits = [t for t in _rate_hits.get(ip, []) if now - t < RATE_LIMIT_WINDOW]
        if len(hits) >= RATE_LIMIT_MAX:
            _rate_hits[ip] = hits
            return True
        hits.append(now)
        _rate_hits[ip] = hits
        # Opportunistic cleanup so the dict can't grow unbounded.
        if len(_rate_hits) > 256:
            for k in [k for k, v in _rate_hits.items() if all(now - t >= RATE_LIMIT_WINDOW for t in v)]:
                _rate_hits.pop(k, None)
        return False

def wiw_error_message(payload, fallback='WIW request failed'):
    """Pull a human-readable reason out of a WIW error payload (dict or JSON string)."""
    try:
        d = payload if isinstance(payload, dict) else json.loads(payload)
        errs = d.get('errors')
        if isinstance(errs, list) and errs:
            return errs[0].get('message') or errs[0].get('code') or fallback
        return d.get('message') or d.get('error') or fallback
    except Exception:
        return fallback

CORS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    # Chrome Private Network Access: a file:// or public page calling a private
    # IP (127.0.0.1) is blocked unless the preflight opts in with this header.
    'Access-Control-Allow-Private-Network': 'true',
}

def send_json(handler, code, body, extra_headers=None):
    data = json.dumps(body, default=str).encode()
    handler.send_response(code)
    for k, v in CORS.items():
        handler.send_header(k, v)
    handler.send_header('Content-Type', 'application/json')
    # Never let the browser cache API responses — this is why "Sync" could show
    # stale numbers: a cached GET to /members or /invoices was reused.
    handler.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
    handler.send_header('Pragma', 'no-cache')
    handler.send_header('Expires', '0')
    for k, v in (extra_headers or {}).items():
        handler.send_header(k, v)
    handler.send_header('Content-Length', len(data))
    handler.end_headers()
    handler.wfile.write(data)

def rgp_get(path, user, key, params=None):
    creds = base64.b64encode(f'{user}:{key}'.encode()).decode()
    headers = {
        'Authorization': f'Basic {creds}',
        'Content-Type': 'application/json',
        'User-Agent': 'OperatorOS/3.1',
        'Accept': 'application/json',
    }
    p = dict(params or {})
    if 'page' not in p: p['page'] = 1
    if 'pageSize' not in p: p['pageSize'] = 200
    url = f'https://api.rockgympro.com{path}?' + urllib.parse.urlencode(p)
    print(f'  RGP → {url}')
    req = urllib.request.Request(url, headers=headers)
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
            raw = r.read().decode('utf-8', 'ignore')
            print(f'  RGP ← {r.status} ({len(raw)} bytes)')
            d = json.loads(raw)
            # Auto-paginate
            list_key = next((k for k, v in d.items() if isinstance(v, list) and k != 'errors'), None)
            if list_key:
                all_records = list(d[list_key])
                total = int(d.get('total', d.get('totalCount', d.get('count', len(all_records)))) or 0)
                page = 2
                while len(all_records) < total and page <= 50:
                    p['page'] = page
                    url2 = f'https://api.rockgympro.com{path}?' + urllib.parse.urlencode(p)
                    req2 = urllib.request.Request(url2, headers=headers)
                    try:
                        with urllib.request.urlopen(req2, timeout=20, context=ctx) as r2:
                            d2 = json.loads(r2.read().decode('utf-8','ignore'))
                            more = d2.get(list_key, [])
                            if not more: break
                            all_records.extend(more)
                    except: break
                    page += 1
                d[list_key] = all_records
                d['_fetched'] = len(all_records)
            return r.status, d
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', 'ignore')
        print(f'  RGP ← HTTP {e.code}: {raw[:300]}')
        try:    return e.code, json.loads(raw)
        except: return e.code, {'error': raw[:500], 'http_status': e.code}
    except Exception as ex:
        print(f'  RGP ← ERROR: {ex}')
        return 500, {'error': str(ex)}

def rgp_request(path, user, key, params=None, verbose=True):
    """
    Single RGP GET with NO auto-injected params (page/pageSize) and detailed
    logging of the exact URL, status and raw body. Used by the checkins
    endpoints, whose RGP contract differs from the other resources:
      • date filters are startDateTime/endDateTime in 'YYYY-MM-DD HH:MM:SS'
        format (a SPACE separator — must be %20-encoded; '+' returns 400)
      • pagination uses 'limit' (10-200) + 'page', NOT 'pageSize'
    Returns (status, parsed_dict, raw_text).
    """
    creds = base64.b64encode(f'{user}:{key}'.encode()).decode()
    headers = {
        'Authorization': f'Basic {creds}',
        'User-Agent': 'OperatorOS/3.2',
        'Accept': 'application/json',
    }
    # quote (NOT quote_plus) so a space becomes %20 — RGP rejects '+' with 400.
    qs = ('?' + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)) if params else ''
    url = f'https://api.rockgympro.com{path}{qs}'
    if verbose: print(f'  RGP → {url}')
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=25, context=ctx) as r:
            raw = r.read().decode('utf-8', 'ignore')
            if verbose: print(f'  RGP ← {r.status} ({len(raw)} bytes): {raw[:600]}')
            try:    return r.status, json.loads(raw), raw
            except: return r.status, {'error': 'non-json response', 'raw': raw[:600]}, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', 'ignore')
        if verbose: print(f'  RGP ← HTTP {e.code}: {raw[:600]}')
        try:    return e.code, json.loads(raw), raw
        except: return e.code, {'error': raw[:600], 'http_status': e.code}, raw
    except Exception as ex:
        if verbose: print(f'  RGP ← ERROR: {type(ex).__name__}: {ex}')
        return 500, {'error': str(ex)}, ''

# Matches 'YYYY-MM-DD HH:MM' inside any checkin field so we can aggregate
# regardless of the exact field name RGP uses for the timestamp.
CHECKIN_DT_RE = re.compile(r'(\d{4}-\d{2}-\d{2})[ T](\d{2}):\d{2}')

def checkin_datetime(rec):
    """Return (date_str, hour_int) for a checkin record, or (None, None)."""
    if not isinstance(rec, dict):
        return None, None
    preferred = ('checkinDateTime', 'checkin_datetime', 'checkInDateTime',
                 'checkinDate', 'checkin_date', 'dateTime', 'datetime',
                 'date', 'time', 'createdDate', 'timestamp')
    for key in preferred:
        v = rec.get(key)
        if v:
            m = CHECKIN_DT_RE.search(str(v))
            if m:
                return m.group(1), int(m.group(2))
    for v in rec.values():
        if isinstance(v, str):
            m = CHECKIN_DT_RE.search(v)
            if m:
                return m.group(1), int(m.group(2))
    return None, None

CHECKINS_HINT = (
    "RGP returned an error for the check-ins endpoint. The request matches the RGP "
    "OpenAPI spec (startDateTime/endDateTime as 'YYYY-MM-DD HH:MM:SS', limit<=200), so this "
    "usually means check-in/check-out tracking is not enabled for this facility, or the API key "
    "was generated without the 'Check-ins' scope. Verify in RGP: Manage -> Settings -> Integration "
    "(API key permissions) and that Check-In/Out is enabled for the facility."
)

def fetch_checkins(fc, user, key, start_date, end_date, max_pages=60):
    """
    Fetch all checkins between two date strings (YYYY-MM-DD), paginating with
    limit=200 + page until a short page is returned.
    Returns (status, last_response_dict, all_records).
    """
    all_records = []
    last = {}
    status = 200
    for page in range(1, max_pages + 1):
        s, d, _raw = rgp_request(f'/v1/checkins/facility/{fc}', user, key, {
            'startDateTime': f'{start_date} 00:00:00',
            'endDateTime':   f'{end_date} 23:59:59',
            'limit': 200,
            'page': page,
        })
        status, last = s, d
        if s != 200:
            return s, d, all_records
        recs = d.get('checkins', d.get('checkin', d.get('data', [])))
        if isinstance(recs, dict): recs = list(recs.values())
        if not isinstance(recs, list): recs = []
        all_records.extend(recs)
        if len(recs) < 200:
            break
    return status, last, all_records

def fetch_all(path, user, key, start_dt, end_dt, list_key, max_pages=40):
    """
    Fetch every record of a resource over a datetime window using the RGP
    spec params (startDateTime/endDateTime + limit/page). Stops at the
    reported pageTotal or the first short page. Returns a list of records.
    """
    out = []
    for page in range(1, max_pages + 1):
        s, d, _raw = rgp_request(path, user, key, {
            'startDateTime': start_dt, 'endDateTime': end_dt, 'limit': 200, 'page': page,
        })
        if s != 200 or not isinstance(d, dict):
            break
        recs = d.get(list_key, [])
        if isinstance(recs, dict): recs = list(recs.values())
        if not isinstance(recs, list) or not recs:
            break
        out.extend(recs)
        paging = d.get('rgpApiPaging') or {}
        try:
            if paging.get('pageTotal') and page >= int(paging['pageTotal']):
                break
        except (ValueError, TypeError):
            pass
        if len(recs) < 200:
            break
    return out

class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        ts = datetime.datetime.now().strftime('%H:%M:%S')
        print(f'[{ts}] {self.path[:80]}')

    def client_ip(self):
        """Real client IP for rate limiting. Behind Railway the socket peer is the
        router, so prefer the first X-Forwarded-For hop when present."""
        xff = self.headers.get('X-Forwarded-For', '')
        if xff:
            return xff.split(',')[0].strip()
        return self.client_address[0]

    def do_OPTIONS(self):
        self.send_response(200)
        for k, v in CORS.items(): self.send_header(k, v)
        self.end_headers()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if rate_limited(self.client_ip()):
            send_json(self, 429, {'error': 'Rate limit exceeded — slow down'},
                      extra_headers={'Retry-After': str(RATE_LIMIT_WINDOW)})
            return

        # CONFIG SET — store credentials so they live on the server, never in the
        # browser. Two backends:
        #   • Local: written to rgp_proxy_config.json (persists across restarts).
        #   • Hosted (Railway): set as process environment variables so they take
        #     effect immediately. NOTE: Railway's filesystem/process env is reset
        #     on redeploy, so for permanent hosted creds also set them in the
        #     Railway dashboard (or via `railway variables`). load_config() reads
        #     env vars first, so dashboard vars and these runtime vars both work.
        # Auth: localhost is trusted. Remote callers (the public Railway URL) must
        # present the admin token (ADMIN_TOKEN env var) so the endpoint is not an
        # open door to overwrite credentials.
        if path == '/config/set':
            real_ip  = self.client_address[0]
            is_local = real_ip in ('127.0.0.1', '::1', 'localhost')
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length).decode()) if length else {}
            except Exception:
                body = {}
            if not is_local:
                admin = os.environ.get('ADMIN_TOKEN', '')
                provided = self.headers.get('X-Admin-Token', '') or body.get('admin_token', '')
                if not admin or provided != admin:
                    send_json(self, 403, {'error': 'Forbidden',
                                          'message': 'Admin token required to set credentials on the hosted proxy'})
                    return
            try:
                allowed = ('rgp_user', 'rgp_key', 'facility_code', 'claude_key',
                           'wiw_email', 'wiw_password', 'gym', 'location')
                applied = {}
                for key in allowed:
                    if key in body and str(body[key]) != '':
                        applied[key] = str(body[key])
                        # Set as a real process env var (satisfies "store as env
                        # variables") so load_config() picks it up immediately.
                        os.environ[ENV_MAP[key]] = str(body[key])
                persisted = False
                if is_local:
                    # Only persist to disk locally — the hosted filesystem is
                    # ephemeral so writing there would be misleading.
                    try:
                        cfg = {}
                        try:
                            with open(CONFIG_FILE, 'r') as f: cfg = json.load(f) or {}
                        except Exception: pass
                        cfg.update(applied)
                        save_config(cfg)
                        persisted = True
                    except Exception:
                        persisted = False
                cfg = load_config()
                send_json(self, 200, {
                    'ok': True,
                    'persisted_to_file': persisted,
                    'hosted': is_hosted(),
                    'note': ('Saved to local config file.' if persisted else
                             'Applied to the running server. On Railway, also set these as '
                             'dashboard environment variables so they survive a redeploy.'),
                    'status': {
                        'rgp':    bool(cfg.get('rgp_user') and cfg.get('rgp_key')),
                        'claude': bool(cfg.get('claude_key')),
                        'wiw':    bool(cfg.get('wiw_email') and cfg.get('wiw_password')),
                    },
                })
            except Exception as e:
                send_json(self, 500, {'error': 'Could not save config', 'detail': str(e)})
            return

        if path == '/ai/call':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = json.loads(self.rfile.read(length).decode())
                # SECURITY: prefer the Claude key from the proxy config; the
                # browser no longer sends it. Body key kept as a fallback only.
                api_key = load_config().get('claude_key', '') or body.get('api_key', '')
                prompt = body.get('prompt', '')
                model = body.get('model', 'claude-sonnet-4-6')
                max_tokens = body.get('max_tokens', 1000)
                system = body.get('system', '')
                messages = body.get('messages')
                # Accept either a single prompt or a full messages array (for multi-turn chat)
                if not messages:
                    messages = [{'role': 'user', 'content': prompt}]
                if not api_key:
                    send_json(self, 400, {'error': 'No Claude API key configured',
                                          'detail': 'Add your Claude API key in Settings (stored in the proxy config).'})
                    return
                if not messages:
                    send_json(self, 400, {'error': 'Missing prompt/messages'})
                    return

                payload = {
                    'model': model,
                    'max_tokens': max_tokens,
                    'messages': messages,
                }
                if system:
                    payload['system'] = system

                ai_req = urllib.request.Request(
                    'https://api.anthropic.com/v1/messages',
                    data=json.dumps(payload).encode(),
                    headers={
                        'Content-Type': 'application/json',
                        'x-api-key': api_key,
                        'anthropic-version': '2023-06-01'
                    },
                    method='POST'
                )
                ctx = ssl.create_default_context()
                with urllib.request.urlopen(ai_req, timeout=30, context=ctx) as resp:
                    ai_data = json.loads(resp.read().decode())
                text = ''
                if ai_data.get('content') and len(ai_data['content']) > 0:
                    text = ai_data['content'][0].get('text', '')
                send_json(self, 200, {'text': text})
            except urllib.error.HTTPError as e:
                detail = e.read().decode()[:500]
                print(f'  AI ✗ HTTPError {e.code}: {detail}')
                send_json(self, e.code, {'error': 'AI request failed', 'detail': detail})
            except Exception as e:
                print(f'  AI ✗ Exception: {type(e).__name__}: {str(e)}')
                send_json(self, 500, {'error': 'AI proxy error', 'detail': str(e)})
            return

        send_json(self, 404, {'error': f'Unknown POST path: {path}'})

    def get_creds(self, params):
        # SECURITY: RGP credentials come ONLY from the proxy config, never from
        # the browser/query string. facility_code is not secret, so it may be
        # passed in the query to switch facilities.
        cfg = load_config()
        u  = cfg.get('rgp_user', '')
        k  = cfg.get('rgp_key',  '')
        fc = (params.get('facility_code') or [None])[0] or cfg.get('facility_code', 'ASP')
        return u.strip(), k.strip(), fc.strip()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        path   = parsed.path

        if rate_limited(self.client_ip()):
            send_json(self, 429, {'error': 'Rate limit exceeded — slow down'},
                      extra_headers={'Retry-After': str(RATE_LIMIT_WINDOW)})
            return

        if path == '/health':
            send_json(self, 200, {'status': 'ok', 'version': '3.3', 'service': 'OperatorOS RGP Proxy'})
            return

        # CONFIG STATUS — booleans only, so the UI can tell whether credentials
        # are configured without ever receiving the secrets themselves.
        if path == '/config/status':
            cfg = load_config()
            send_json(self, 200, {
                'rgp':    bool(cfg.get('rgp_user') and cfg.get('rgp_key')),
                'claude': bool(cfg.get('claude_key')),
                'wiw':    bool(cfg.get('wiw_email') and cfg.get('wiw_password')),
                'facility_code': cfg.get('facility_code', 'ASP'),
                'gym':    cfg.get('gym', ''),
                'hosted': is_hosted(),
            })
            return

        # WHEN I WORK — proxied to avoid browser CORS blocks. Credentials come
        # from the proxy config (kept out of the browser); query params remain
        # accepted as a fallback for backwards compatibility.
        if path == '/wiw/shifts':
            _wcfg    = load_config()
            email    = (params.get('email') or [None])[0] or _wcfg.get('wiw_email')
            password = (params.get('password') or [None])[0] or _wcfg.get('wiw_password')
            days     = int((params.get('days') or ['21'])[0])
            if not email or not password:
                send_json(self, 401, {'error': 'WIW not configured',
                                      'message': 'Add When I Work email/password in Settings'})
                return
            try:
                # Disable cert verification (matches rgp_get) — avoids flaky
                # SSL failures on Windows that made WIW sync unreliable.
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE

                print(f'  WIW → logging in as {email}')
                login_req = urllib.request.Request(
                    'https://api.login.wheniwork.com/login',
                    data=json.dumps({'email': email, 'password': password}).encode(),
                    headers={'Content-Type': 'application/json', 'W-Key': 'knowledgebase'},
                    method='POST'
                )
                with urllib.request.urlopen(login_req, timeout=20, context=ctx) as resp:
                    login_data = json.loads(resp.read().decode())
                print(f'  WIW ← login response keys: {list(login_data.keys())}')
                token = login_data.get('token') or (login_data.get('login') or {}).get('token')
                if not token:
                    print(f'  WIW ✗ no token in response: {login_data}')
                    send_json(self, 401, {
                        'error': 'WIW login failed',
                        'message': wiw_error_message(login_data, 'Incorrect WIW email or password'),
                        'detail': login_data,
                    })
                    return
                print(f'  WIW ✓ got token, fetching users + shifts')

                # Build user_id -> name map so each shift can be labelled with
                # the staff member's name in the OperatorOS calendar.
                users = {}
                try:
                    users_req = urllib.request.Request(
                        'https://api.wheniwork.com/2/users',
                        headers={'W-Token': token, 'Accept': 'application/json'}
                    )
                    with urllib.request.urlopen(users_req, timeout=20, context=ctx) as ur:
                        udata = json.loads(ur.read().decode())
                    for u in udata.get('users', []):
                        nm = (str(u.get('first_name', '')).strip() + ' ' + str(u.get('last_name', '')).strip()).strip()
                        users[str(u.get('id'))] = nm or u.get('email', '') or ('User ' + str(u.get('id')))
                    print(f'  WIW ← {len(users)} users')
                except Exception as ue:
                    print(f'  WIW ⚠ user fetch failed (shifts will use ids): {ue}')

                start = datetime.date.today().isoformat()
                end   = (datetime.date.today() + datetime.timedelta(days=days)).isoformat()
                shifts_req = urllib.request.Request(
                    f'https://api.wheniwork.com/2/shifts?start={start}&end={end}',
                    headers={'W-Token': token, 'Accept': 'application/json'}
                )
                with urllib.request.urlopen(shifts_req, timeout=20, context=ctx) as resp2:
                    shifts_data = json.loads(resp2.read().decode())
                shifts = shifts_data.get('shifts', []) or []
                # Some WIW responses embed related users — fold them into the map.
                for u in shifts_data.get('users', []):
                    nm = (str(u.get('first_name', '')).strip() + ' ' + str(u.get('last_name', '')).strip()).strip()
                    users.setdefault(str(u.get('id')), nm or ('User ' + str(u.get('id'))))
                # Attach a resolved staff_name to every shift for the UI.
                for sh in shifts:
                    uid = str(sh.get('user_id', sh.get('userId', '')))
                    if uid in ('', '0', 'None'):
                        sh['staff_name'] = 'Open shift'
                    else:
                        sh['staff_name'] = users.get(uid, 'User ' + uid)
                print(f'  WIW ← {len(shifts)} shifts')
                send_json(self, 200, {'shifts': shifts, 'users': users, 'total': len(shifts)})
            except urllib.error.HTTPError as e:
                detail = e.read().decode()[:300]
                print(f'  WIW ✗ HTTPError {e.code}: {detail}')
                send_json(self, e.code, {
                    'error': 'WIW request failed',
                    'message': wiw_error_message(detail, f'WIW API error (HTTP {e.code})'),
                    'detail': detail,
                })
            except Exception as e:
                print(f'  WIW ✗ Exception: {type(e).__name__}: {str(e)}')
                send_json(self, 500, {
                    'error': 'WIW proxy error',
                    'message': f'{type(e).__name__}: {e}',
                    'detail': str(e),
                })
            return

        u, k, fc = self.get_creds(params)
        if not u or not k:
            send_json(self, 401, {'error': 'No RGP credentials found. Check rgp_proxy_config.json'})
            return

        # MEMBERS — Nicole confirmed: /v1/customers/facility/{facilityCode}
        if path == '/members':
            # Sort by most recent visit to get active members first
            s, d = rgp_get(f'/v1/customers/facility/{fc}', u, k, {
                'orderBy': 'lastVisitDate',
                'orderDir': 'desc',
                'pageSize': 500,  # Get top 500 most recent visitors
            })
            if s == 200:
                raw = d.get('customers', d.get('customer', d.get('data', d.get('results', []))))
                if isinstance(raw, dict): raw = list(raw.values())
                today = datetime.date.today()
                cutoff_30 = today - datetime.timedelta(days=30)
                cutoff_60 = today - datetime.timedelta(days=60)

                def calc_status(c):
                    exp = c.get('membership_exp', c.get('membershipExpDate', c.get('expirationDate', '')))
                    lv  = c.get('last_visit', c.get('lastVisitDate', c.get('lastVisit', '')))
                    raw_status = c.get('status', c.get('customerStatus', ''))
                    if raw_status in ('TERMINATED', 'FROZEN', 'EXPIRED'):
                        return raw_status
                    # Derive from expiry date
                    if exp and exp not in ('0000-00-00', '', None):
                        try:
                            exp_date = datetime.date.fromisoformat(str(exp)[:10])
                            if exp_date < today:
                                return 'EXPIRED'
                            return 'OK'
                        except: pass
                    # Derive from last visit
                    if lv and lv not in ('0000-00-00', '', None):
                        try:
                            lv_date = datetime.date.fromisoformat(str(lv)[:10])
                            if lv_date >= cutoff_30:
                                return 'OK'
                            if lv_date >= cutoff_60:
                                return 'AT_RISK'
                            return 'LAPSED'
                        except: pass
                    return 'UNKNOWN'

                members = [{
                    'id':            c.get('id', c.get('guid', c.get('customerGuid', ''))),
                    'first_name':    c.get('first_name', c.get('firstName', '')),
                    'last_name':     c.get('last_name', c.get('lastName', '')),
                    'email':         c.get('email', ''),
                    'status':        calc_status(c),
                    'membership':    c.get('membership', c.get('membershipName', '')),
                    'membership_exp':c.get('membership_exp', c.get('membershipExpDate', c.get('expirationDate', ''))),
                    'last_visit':    c.get('last_visit', c.get('lastVisitDate', c.get('lastVisit', ''))),
                    'join_date':     c.get('join_date', c.get('joinDate', c.get('createdDate', ''))),
                    'visits_total':  c.get('visits_total', c.get('visitCount', c.get('totalVisits', 0))),
                } for c in raw]
                send_json(self, 200, {'members': members, 'total': len(members), 'raw_keys': list(d.keys())})
            else:
                send_json(self, s, {'error': d, 'path_tried': f'/v1/customers/facility/{fc}'})
            return

        # BOOKINGS — Nicole confirmed: /v1/bookings/facility/{facilityCode}
        if path == '/bookings/summary':
            today    = datetime.date.today().isoformat()
            start_yr = datetime.date(datetime.date.today().year, 1, 1).isoformat()
            s, d = rgp_get(f'/v1/bookings/facility/{fc}', u, k, {
                'startDate': start_yr,
                'endDate':   today,
                'orderBy':   'bookingDate',
                'orderDir':  'desc',
                'pageSize':  500,
            })
            if s == 200:
                raw = d.get('bookings', d.get('booking', d.get('data', [])))
                programs = {}
                for b in raw:
                    name = (b.get('originalBookedOfferingName') or b.get('offeringName') or b.get('courseName') or b.get('name') or 'Unknown')
                    if name not in programs:
                        programs[name] = {'name': name, 'bookings': 0, 'cancelled': 0, 'revenue': 0.0}
                    if b.get('cancelled') == 1 or str(b.get('cancellationStatus','')).upper() in ('CANCELLED','CANCELED'):
                        programs[name]['cancelled'] += 1
                    else:
                        programs[name]['bookings'] += int(b.get('participantCount', b.get('quantity', 1)) or 1)
                        programs[name]['revenue']  += float(b.get('price', b.get('amount', 0)) or 0)
                summary = sorted(programs.values(), key=lambda x: x['revenue'], reverse=True)
                send_json(self, 200, {'programs': summary, 'total_programs': len(summary), 'raw_keys': list(d.keys())})
            else:
                send_json(self, s, {'error': d, 'path_tried': f'/v1/bookings/facility/{fc}'})
            return

        # RAW BOOKING DEBUG — shows exact field names from RGP
        if path == '/debug/booking':
            s, d = rgp_get(f'/v1/bookings/facility/{fc}', u, k, {'pageSize': 1})
            if s == 200:
                raw = d.get('bookings', d.get('booking', d.get('data', [])))
                send_json(self, 200, {
                    'first_record': raw[0] if raw else {},
                    'all_keys': list(raw[0].keys()) if raw else [],
                    'total_available': d.get('rgpApiPaging', {}).get('itemTotal', 0),
                })
            else:
                send_json(self, s, d)
            return

        # RAW INVOICE DEBUG — shows exact field names from RGP
        if path == '/debug/invoice':
            s, d = rgp_get(f'/v1/invoices/facility/{fc}', u, k, {'pageSize': 1})
            if s == 200:
                raw = d.get('invoices', d.get('invoice', d.get('data', [])))
                send_json(self, 200, {
                    'first_record': raw[0] if raw else {},
                    'all_keys': list(raw[0].keys()) if raw else [],
                })
            else:
                send_json(self, s, d)
            return

        # INVOICES — /v1/invoices/facility/{fc}. RGP filters by startDateTime/
        # endDateTime ('YYYY-MM-DD HH:MM:SS'); the old startDate/endDate params
        # were silently ignored, so the endpoint returned the OLDEST invoices
        # (2016) instead of the last 30 days. fetch_all uses the correct params.
        if path == '/invoices':
            today     = datetime.date.today()
            today_str = today.isoformat()
            start_30  = (today - datetime.timedelta(days=30)).isoformat()
            raw = fetch_all(f'/v1/invoices/facility/{fc}', u, k,
                            f'{start_30} 00:00:00', f'{today_str} 23:59:59', 'invoices')
            # Filter out voided invoices for accurate revenue.
            valid = [i for i in raw if not i.get('voidedInvoice', 0)]
            total_rev = sum(float(i.get('amount', 0) or 0) for i in valid)
            today_count = sum(1 for i in valid
                              if str(i.get('invoicePostDate', ''))[:10] == today_str)
            today_rev = round(sum(float(i.get('amount', 0) or 0) for i in valid
                                  if str(i.get('invoicePostDate', ''))[:10] == today_str), 2)
            invoices = [{
                'date':    i.get('invoicePostDate', ''),
                'type':    i.get('invtype', ''),
                'amount':  float(i.get('amount', 0) or 0),
                'tax':     float(i.get('salesTax', 0) or 0),
                'source':  (i.get('payment') or {}).get('source', ''),
                'voided':  bool(i.get('voidedInvoice', 0)),
                'memo':    i.get('memo', ''),
            } for i in raw]
            invoices.sort(key=lambda x: x['date'], reverse=True)  # newest first
            send_json(self, 200, {
                'invoices': invoices,
                'total': len(invoices),
                'valid_count': len(valid),
                'total_revenue': round(total_rev, 2),
                'today_count': today_count,
                'today_revenue': today_rev,
                'date_start': start_30,
                'date_end': today_str,
            })
            return

        # INTELLIGENCE — this month vs last month, for trend comparison
        if path == '/intel/monthly':
            today = datetime.date.today()
            this_month_start = today.replace(day=1)
            last_month_end = this_month_start - datetime.timedelta(days=1)
            last_month_start = last_month_end.replace(day=1)

            s1, d1 = rgp_get(f'/v1/invoices/facility/{fc}', u, k, {
                'startDate': last_month_start.isoformat(),
                'endDate':   today.isoformat(),
                'orderBy':   'invoicePostDate',
                'orderDir':  'desc',
                'pageSize':  500,
            })
            s2, d2 = rgp_get(f'/v1/bookings/facility/{fc}', u, k, {
                'startDate': last_month_start.isoformat(),
                'endDate':   today.isoformat(),
                'orderBy':   'bookingDate',
                'orderDir':  'desc',
                'pageSize':  500,
            })

            this_month_rev, last_month_rev = 0.0, 0.0
            this_month_inv, last_month_inv = 0, 0
            if s1 == 200:
                raw = d1.get('invoices', d1.get('invoice', d1.get('data', [])))
                for i in raw:
                    if i.get('voidedInvoice', 0):
                        continue
                    dt = (i.get('invoicePostDate') or '')[:10]
                    amt = float(i.get('amount', 0) or 0)
                    if dt >= this_month_start.isoformat():
                        this_month_rev += amt; this_month_inv += 1
                    elif dt >= last_month_start.isoformat():
                        last_month_rev += amt; last_month_inv += 1

            this_month_book, last_month_book = 0, 0
            this_month_cancel, last_month_cancel = 0, 0
            if s2 == 200:
                raw2 = d2.get('bookings', d2.get('booking', d2.get('data', [])))
                for b in raw2:
                    dt = (b.get('bookingDate') or '')[:10]
                    cancelled = b.get('cancelled') or b.get('isCancelled')
                    if dt >= this_month_start.isoformat():
                        this_month_book += 1
                        if cancelled: this_month_cancel += 1
                    elif dt >= last_month_start.isoformat():
                        last_month_book += 1
                        if cancelled: last_month_cancel += 1

            send_json(self, 200, {
                'this_month': {
                    'label': today.strftime('%B %Y'),
                    'revenue': round(this_month_rev, 2),
                    'invoices': this_month_inv,
                    'bookings': this_month_book,
                    'cancellations': this_month_cancel,
                },
                'last_month': {
                    'label': last_month_start.strftime('%B %Y'),
                    'revenue': round(last_month_rev, 2),
                    'invoices': last_month_inv,
                    'bookings': last_month_book,
                    'cancellations': last_month_cancel,
                },
                'revenue_change_pct': round(((this_month_rev - last_month_rev) / last_month_rev * 100), 1) if last_month_rev else None,
                'booking_change_pct': round(((this_month_book - last_month_book) / last_month_book * 100), 1) if last_month_book else None,
            })
            return

        # CHECKINS ACTIVE — /v1/checkins/active/facility/{fc} (takes NO query params)
        if path == '/checkins/active':
            s, d, _raw = rgp_request(f'/v1/checkins/active/facility/{fc}', u, k, None)
            if s == 200:
                # RGP returns the active count; tolerate several response shapes.
                cnt = d.get('count', d.get('activeCount', d.get('active', d.get('data'))))
                if isinstance(cnt, list): cnt = len(cnt)
                if not isinstance(cnt, int):
                    try:    cnt = int(cnt)
                    except: cnt = 0
                send_json(self, 200, {'active_now': cnt, 'rgp_raw': d})
            else:
                send_json(self, s, {
                    'active_now': 0, 'rgp_status': s,
                    'rgp_message': d.get('message') if isinstance(d, dict) else None,
                    'error': d, 'path_tried': f'/v1/checkins/active/facility/{fc}',
                    'hint': CHECKINS_HINT,
                })
            return

        # CHECKINS TODAY — /v1/checkins/facility/{fc} for the current day
        if path == '/checkins/today':
            today_str = datetime.date.today().isoformat()
            s, d, recs = fetch_checkins(fc, u, k, today_str, today_str)
            if s == 200:
                send_json(self, 200, {
                    'count': len(recs), 'date': today_str,
                    'checkins': recs[:500],
                    'sample_record': recs[0] if recs else None,
                })
            else:
                send_json(self, s, {
                    'count': 0, 'rgp_status': s,
                    'rgp_message': d.get('message') if isinstance(d, dict) else None,
                    'error': d, 'path_tried': f'/v1/checkins/facility/{fc}',
                    'hint': CHECKINS_HINT,
                })
            return

        # CHECKINS HISTORY — /v1/checkins/facility/{fc} over a date range
        if path == '/checkins/history':
            days  = int((params.get('days') or ['30'])[0])
            end   = datetime.date.today()
            start = end - datetime.timedelta(days=days)
            s, d, recs = fetch_checkins(fc, u, k, start.isoformat(), end.isoformat())
            if s == 200:
                daily = {}; hourly = {}; dow = {0:0,1:0,2:0,3:0,4:0,5:0,6:0}
                for c in recs:
                    ds, h = checkin_datetime(c)
                    if ds:
                        daily[ds] = daily.get(ds, 0) + 1
                        try:
                            dt = datetime.date.fromisoformat(ds)
                            dow[dt.weekday()] = dow.get(dt.weekday(), 0) + 1
                        except: pass
                    if h is not None and 0 <= h <= 23:
                        hourly[h] = hourly.get(h, 0) + 1
                send_json(self, 200, {
                    'total': len(recs), 'days': days,
                    'daily_counts': daily, 'hourly_distribution': hourly,
                    'day_of_week_counts': dow,
                    'avg_per_day': round(len(recs)/days, 1) if days else 0,
                    'sample_record': recs[0] if recs else None,
                })
            else:
                send_json(self, s, {
                    'error': d, 'rgp_status': s,
                    'rgp_message': d.get('message') if isinstance(d, dict) else None,
                    'total': 0, 'hourly_distribution': {}, 'day_of_week_counts': {},
                    'path_tried': f'/v1/checkins/facility/{fc}',
                    'hint': CHECKINS_HINT,
                })
            return

        # TRAFFIC HEATMAP (FALLBACK) — approximate floor traffic from invoice +
        # booking timestamps while the RGP check-ins API is unavailable.
        #   • Invoices: in-person sales (invoicePostDate) = desk/drop-in/retail
        #     presence. ONLINE + voided invoices are excluded (not floor traffic).
        #   • Bookings: scheduled session time (originalBookedTime) = class/party
        #     attendance, weighted by participantCount and limited to sessions
        #     that actually occurred inside the window.
        # Returns the same shape as /checkins/history so the heatmap reuses it.
        if path == '/traffic/heatmap':
            days  = int((params.get('days') or ['30'])[0])
            end   = datetime.date.today()
            start = end - datetime.timedelta(days=days)
            start_str, end_str = start.isoformat(), end.isoformat()
            start_dt, end_dt = f'{start_str} 00:00:00', f'{end_str} 23:59:59'

            hourly = {}; dow = {0:0,1:0,2:0,3:0,4:0,5:0,6:0}; daily = {}
            sources = {'invoices': 0, 'bookings': 0}

            def add_event(dtstr, weight=1):
                m = CHECKIN_DT_RE.search(str(dtstr))
                if not m:
                    return False
                ds, h = m.group(1), int(m.group(2))
                if ds < start_str or ds > end_str:
                    return False
                daily[ds] = daily.get(ds, 0) + weight
                if 0 <= h <= 23:
                    hourly[h] = hourly.get(h, 0) + weight
                try:
                    dt = datetime.date.fromisoformat(ds)
                    dow[dt.weekday()] = dow.get(dt.weekday(), 0) + weight
                except ValueError:
                    pass
                return True

            # In-person invoices → floor presence at the desk.
            for inv in fetch_all(f'/v1/invoices/facility/{fc}', u, k, start_dt, end_dt, 'invoices'):
                if inv.get('voidedInvoice'):
                    continue
                if str(inv.get('invtype', '')).upper() == 'ONLINE':
                    continue
                if add_event(inv.get('invoicePostDate')):
                    sources['invoices'] += 1

            # Booked sessions → class/party attendance (weighted by headcount).
            for bk in fetch_all(f'/v1/bookings/facility/{fc}', u, k, start_dt, end_dt, 'bookings'):
                if bk.get('cancelled'):
                    continue
                try:    pax = max(1, int(bk.get('participantCount', 1) or 1))
                except (ValueError, TypeError): pax = 1
                if add_event(bk.get('originalBookedTime'), pax):
                    sources['bookings'] += 1

            total = sum(hourly.values())
            send_json(self, 200, {
                'total': total, 'days': days,
                'daily_counts': daily, 'hourly_distribution': hourly,
                'day_of_week_counts': dow,
                'avg_per_day': round(total / days, 1) if days else 0,
                'source': 'estimated',
                'derived_from': sources,
                'note': 'Estimated floor traffic from in-person sales and booked sessions '
                        '(RGP check-ins API not yet available).',
            })
            return

        # DASHBOARD — single call for home screen numbers
        if path == '/dashboard':
            today    = datetime.date.today().isoformat()
            start_30 = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
            def safe(fn):
                try:   return fn()
                except: return (500, {})
            # Checkins use the dedicated request path (startDateTime/endDateTime, limit).
            try:    s1, d1, _r1 = rgp_request(f'/v1/checkins/active/facility/{fc}', u, k, None)
            except: s1, d1 = 500, {}
            try:    s2, d2, today_recs = fetch_checkins(fc, u, k, today, today)
            except: s2, today_recs = 500, []
            s3,d3 = safe(lambda: rgp_get(f'/v1/customers/facility/{fc}', u, k, {'pageSize': 1}))
            s4,d4 = safe(lambda: rgp_get(f'/v1/invoices/facility/{fc}', u, k, {'startDate': start_30, 'endDate': today, 'pageSize': 1}))
            active_now   = (d1.get('count', d1.get('activeCount', d1.get('data', 0))) if s1==200 else 0)
            if not isinstance(active_now, int):
                try: active_now = int(active_now)
                except: active_now = 0
            today_list   = today_recs if s2==200 else []
            members_total= int(d3.get('total', d3.get('totalCount', d3.get('count', 0))) or 0) if s3==200 else 0
            rev_total    = float(d4.get('total_revenue', 0) or 0) if s4==200 else 0
            send_json(self, 200, {
                'active_now': active_now,
                'checkins_today': len(today_list),
                'members_total': members_total,
                'revenue_30d': rev_total,
                'facility_code': fc,
                'endpoints': {'active': s1==200, 'today': s2==200, 'members': s3==200, 'invoices': s4==200},
            })
            return

        # DISCOVER — test all confirmed endpoints
        if path == '/discover':
            tests = [
                ('facilities',      '/v1/facilities',                    {}),
                ('customers',       f'/v1/customers/facility/{fc}',      {'pageSize':1}),
                ('bookings',        f'/v1/bookings/facility/{fc}',       {'pageSize':1}),
                ('invoices',        f'/v1/invoices/facility/{fc}',       {'pageSize':1}),
                ('sales',           f'/v1/sales/facility/{fc}',          {'pageSize':1, 'startDate': (datetime.date.today()-datetime.timedelta(days=7)).isoformat(), 'endDate': datetime.date.today().isoformat()}),
                # Checkins use startDateTime/endDateTime ('YYYY-MM-DD HH:MM:SS') + limit, via rgp_request.
                ('checkins',        f'/v1/checkins/facility/{fc}',       {'startDateTime': (datetime.date.today()-datetime.timedelta(days=7)).isoformat()+' 00:00:00', 'endDateTime': datetime.date.today().isoformat()+' 23:59:59', 'limit':10}),
                ('checkins_active', f'/v1/checkins/active/facility/{fc}', None),
            ]
            results = {}
            for name, ep, p in tests:
                if name.startswith('checkins'):
                    s, d, _raw = rgp_request(ep, u, k, p)
                else:
                    s, d = rgp_get(ep, u, k, p or None)
                list_key = next((kk for kk, vv in d.items() if isinstance(vv, list)), None)
                results[name] = {
                    'endpoint': ep, 'status': s, 'working': s==200,
                    'has_data': bool(d.get(list_key)) if list_key else s==200,
                    'keys': list(d.keys())[:10], 'preview': str(d)[:200],
                }
            send_json(self, 200, {'facility_code': fc, 'all_working': all(v['working'] for v in results.values()), 'results': results})
            return

        send_json(self, 404, {'error': f'Unknown: {path}'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    # Hosted (Railway) must bind 0.0.0.0 to be reachable through the router;
    # locally bind 127.0.0.1 only so the proxy isn't exposed on the network.
    # HOST env var overrides if needed.
    host = os.environ.get('HOST') or ('0.0.0.0' if is_hosted() else '127.0.0.1')
    server = HTTPServer((host, port), Handler)
    print('OperatorOS RGP Proxy v3.4')
    print(f'Running on http://{host}:{port}' + ('  [HOSTED]' if is_hosted() else '  [local]'))
    cfg0 = load_config()
    print('Credentials source: ' + ('environment variables' if is_hosted() else 'rgp_proxy_config.json')
          + f"  (RGP={'set' if cfg0.get('rgp_key') else 'MISSING'},"
          + f" Claude={'set' if cfg0.get('claude_key') else 'unset'},"
          + f" WIW={'set' if cfg0.get('wiw_email') else 'unset'})")
    print(f'Rate limit: {RATE_LIMIT_MAX} requests / {RATE_LIMIT_WINDOW}s per IP')
    print('Keep this window open while using OperatorOS.')
    print('---')
    server.serve_forever()
