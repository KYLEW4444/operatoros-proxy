"""
OperatorOS RGP Proxy v3.1
Endpoints confirmed by RGP support (Nicole Menasco, Jun 16 2026)
Fix: proper error logging + exact URL format match from Nicole's docs
"""

import json
import urllib.request
import urllib.parse
import base64
import os
import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = int(os.environ.get('PORT', 5001))

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-RGP-User, X-RGP-Key, X-Facility-Code',
}

def send_json(handler, code, body):
    data = json.dumps(body, default=str).encode()
    handler.send_response(code)
    for k, v in CORS_HEADERS.items():
        handler.send_header(k, v)
    handler.send_header('Content-Type', 'application/json')
    handler.send_header('Content-Length', len(data))
    handler.end_headers()
    handler.wfile.write(data)

def rgp_get(path, rgp_user, rgp_key, params=None):
    """
    Single authenticated GET to RGP API.
    Returns (http_status, parsed_body_dict).
    Auto-paginates through all pages.
    """
    creds = base64.b64encode(f'{rgp_user}:{rgp_key}'.encode()).decode()
    headers = {
        'Authorization': f'Basic {creds}',
        'Content-Type': 'application/json',
        'User-Agent': 'OperatorOS/3.1',
        'Accept': 'application/json',
    }

    def fetch_page(url):
        print(f'  → RGP GET {url}')
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode('utf-8', 'ignore')
                print(f'  ← {resp.status} ({len(raw)} bytes)')
                return resp.status, json.loads(raw)
        except urllib.error.HTTPError as e:
            raw = e.read().decode('utf-8', 'ignore')
            print(f'  ← HTTP {e.code}: {raw[:300]}')
            try:    return e.code, json.loads(raw)
            except: return e.code, {'error': raw[:500], 'http_status': e.code}
        except Exception as ex:
            print(f'  ← EXCEPTION: {ex}')
            return 500, {'error': str(ex)}

    base_url = f'https://api.rockgympro.com{path}'
    p = dict(params or {})
    if 'page' not in p:
        p['page'] = 1
    if 'pageSize' not in p:
        p['pageSize'] = 200

    url = base_url + '?' + urllib.parse.urlencode(p)
    status, data = fetch_page(url)

    if status != 200:
        return status, data

    # Find the list key in the response
    list_key = next((k for k, v in data.items() if isinstance(v, list) and k not in ('errors',)), None)
    if not list_key:
        return status, data

    all_records = list(data[list_key])
    total = data.get('total', data.get('totalCount', data.get('count', len(all_records))))

    # Paginate if needed
    page = 2
    while len(all_records) < int(total or 0) and page <= 50:
        p['page'] = page
        url = base_url + '?' + urllib.parse.urlencode(p)
        s2, d2 = fetch_page(url)
        if s2 != 200 or not d2.get(list_key):
            break
        all_records.extend(d2[list_key])
        page += 1

    data[list_key] = all_records
    data['_fetched'] = len(all_records)
    return 200, data


class ProxyHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        ts = datetime.datetime.now().strftime('%H:%M:%S')
        print(f'[{ts}] {self.path[:80]} → {args[1] if len(args)>1 else ""}')

    def do_OPTIONS(self):
        self.send_response(200)
        for k, v in CORS_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()

    def creds(self, params):
        u  = (params.get('api_user')       or [None])[0] or self.headers.get('X-RGP-User')       or os.environ.get('RGP_USER', '')
        k  = (params.get('api_key')        or [None])[0] or self.headers.get('X-RGP-Key')        or os.environ.get('RGP_KEY', '')
        fc = (params.get('facility_code')  or [None])[0] or self.headers.get('X-Facility-Code')  or ''
        return u.strip(), k.strip(), fc.strip()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        path   = parsed.path

        # ── Health ───────────────────────────────────────────────────────────
        if path == '/health':
            send_json(self, 200, {
                'status': 'ok', 'version': '3.1',
                'service': 'OperatorOS RGP Proxy',
                'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            })
            return

        u, k, fc = self.creds(params)

        if not u or not k:
            send_json(self, 401, {'error': 'Missing RGP credentials. Pass api_user and api_key.'})
            return

        # ── Facilities ───────────────────────────────────────────────────────
        if path == '/facilities':
            s, d = rgp_get('/v1/facilities', u, k)
            if s == 200:
                facs = list(d.get('facilities', {}).values()) if isinstance(d.get('facilities'), dict) else d.get('facilities', [])
                send_json(self, 200, {'facilities': [{
                    'name': f.get('name',''), 'code': f.get('code',''),
                    'address': f.get('address',''), 'city': f.get('city',''),
                    'timezone': f.get('timezone',''),
                } for f in facs], 'count': len(facs)})
            else:
                send_json(self, s, d)
            return

        if not fc:
            send_json(self, 400, {'error': 'facility_code is required', 'hint': 'Add &facility_code=ASP to your request'})
            return

        # ── RAW DEBUG — see exactly what RGP returns ──────────────────────────
        # Visit: /raw/v1/customers/facility/ASP?api_user=X&api_key=Y&facility_code=ASP
        if path.startswith('/raw/'):
            rgp_path = path[4:]  # strip /raw
            extra = {k2: v[0] for k2, v in params.items() if k2 not in ('api_user','api_key','facility_code')}
            s, d = rgp_get(rgp_path, u, k, extra or None)
            send_json(self, s, d)
            return

        # ── Members ──────────────────────────────────────────────────────────
        # Nicole confirmed: GET /v1/customers/facility/{facilityCode}
        if path == '/members':
            extra = {k2: v[0] for k2, v in params.items() if k2 not in ('api_user','api_key','facility_code')}
            s, d = rgp_get(f'/v1/customers/facility/{fc}', u, k, extra or None)
            if s == 200:
                # Try multiple possible key names RGP might use
                raw = d.get('customers', d.get('customer', d.get('data', d.get('results', []))))
                if isinstance(raw, dict):
                    raw = list(raw.values())
                members = [{
                    'id':            c.get('guid', c.get('customerGuid', c.get('id', ''))),
                    'first_name':    c.get('firstName', c.get('first_name', '')),
                    'last_name':     c.get('lastName',  c.get('last_name', '')),
                    'email':         c.get('email', ''),
                    'phone':         c.get('phone', c.get('phoneNumber', '')),
                    'status':        c.get('status', c.get('customerStatus', '')),
                    'customer_type': c.get('customerType', c.get('type', '')),
                    'membership':    c.get('membershipName', c.get('membership', c.get('membershipType', ''))),
                    'membership_exp':c.get('membershipExpDate', c.get('expirationDate', '')),
                    'last_visit':    c.get('lastVisitDate', c.get('lastCheckin', c.get('lastVisit', ''))),
                    'join_date':     c.get('joinDate', c.get('createdDate', '')),
                    'visits_total':  c.get('visitCount', c.get('totalVisits', 0)),
                    'balance':       c.get('balance', c.get('accountBalance', 0)),
                } for c in raw]
                send_json(self, 200, {'members': members, 'total': len(members), 'raw_keys': list(d.keys()), 'facility_code': fc})
            else:
                send_json(self, s, {'error': d, 'rgp_path': f'/v1/customers/facility/{fc}', 'hint': 'Check your facility code and credentials'})
            return

        # ── Members active only ───────────────────────────────────────────────
        if path == '/members/active':
            s, d = rgp_get(f'/v1/customers/facility/{fc}', u, k, {'status': 'OK'})
            if s == 200:
                raw = d.get('customers', d.get('data', []))
                send_json(self, 200, {'members': raw, 'total': len(raw)})
            else:
                send_json(self, s, d)
            return

        # ── Members at risk ───────────────────────────────────────────────────
        if path == '/members/atrisk':
            s, d = rgp_get(f'/v1/customers/facility/{fc}', u, k, {'status': 'OK'})
            if s == 200:
                cutoff = datetime.date.today() - datetime.timedelta(days=30)
                raw = d.get('customers', d.get('data', []))
                at_risk = []
                for c in raw:
                    lv = c.get('lastVisitDate', c.get('lastVisit', ''))
                    if not lv:
                        at_risk.append(c)
                    else:
                        try:
                            if datetime.date.fromisoformat(str(lv)[:10]) < cutoff:
                                at_risk.append(c)
                        except: pass
                send_json(self, 200, {'members': at_risk, 'total': len(at_risk), 'cutoff_days': 30})
            else:
                send_json(self, s, d)
            return

        # ── Bookings ──────────────────────────────────────────────────────────
        # Nicole confirmed: GET /v1/bookings/facility/{facilityCode}
        if path == '/bookings':
            extra = {k2: v[0] for k2, v in params.items() if k2 not in ('api_user','api_key','facility_code')}
            s, d = rgp_get(f'/v1/bookings/facility/{fc}', u, k, extra or None)
            if s == 200:
                raw = d.get('bookings', d.get('booking', d.get('data', [])))
                send_json(self, 200, {'bookings': raw, 'total': len(raw), 'raw_keys': list(d.keys())})
            else:
                send_json(self, s, {'error': d, 'rgp_path': f'/v1/bookings/facility/{fc}'})
            return

        # ── Bookings summary by program ────────────────────────────────────────
        if path == '/bookings/summary':
            s, d = rgp_get(f'/v1/bookings/facility/{fc}', u, k)
            if s == 200:
                raw = d.get('bookings', d.get('booking', d.get('data', [])))
                programs = {}
                for b in raw:
                    name = (b.get('offeringName') or b.get('courseName') or b.get('programName') or b.get('name') or 'Unknown')
                    if name not in programs:
                        programs[name] = {'name': name, 'bookings': 0, 'cancelled': 0, 'revenue': 0.0, 'course_guid': b.get('courseGuid', '')}
                    cancelled = str(b.get('cancellationStatus', '')).upper() in ('CANCELLED', 'CANCELED', 'CANCEL')
                    if cancelled:
                        programs[name]['cancelled'] += 1
                    else:
                        programs[name]['bookings'] += int(b.get('participantCount', b.get('quantity', 1)) or 1)
                        programs[name]['revenue']  += float(b.get('price', b.get('amount', b.get('total', 0))) or 0)
                summary = sorted(programs.values(), key=lambda x: x['revenue'], reverse=True)
                send_json(self, 200, {'programs': summary, 'total_programs': len(summary), 'total_bookings': len(raw), 'raw_keys': list(d.keys())})
            else:
                send_json(self, s, {'error': d, 'rgp_path': f'/v1/bookings/facility/{fc}'})
            return

        # ── Invoices ──────────────────────────────────────────────────────────
        # Nicole confirmed: GET /v1/invoices/facility/{facilityCode}
        if path == '/invoices':
            extra = {k2: v[0] for k2, v in params.items() if k2 not in ('api_user','api_key','facility_code')}
            s, d = rgp_get(f'/v1/invoices/facility/{fc}', u, k, extra or None)
            if s == 200:
                raw = d.get('invoices', d.get('invoice', d.get('data', [])))
                total_rev = sum(float(i.get('amount', i.get('total', 0)) or 0) for i in raw)
                send_json(self, 200, {'invoices': raw, 'total': len(raw), 'total_revenue': round(total_rev, 2), 'raw_keys': list(d.keys())})
            else:
                send_json(self, s, {'error': d, 'rgp_path': f'/v1/invoices/facility/{fc}'})
            return

        # ── Sales ─────────────────────────────────────────────────────────────
        # Nicole confirmed: GET /v1/sales/facility/{facilityCode}
        if path == '/sales':
            extra = {k2: v[0] for k2, v in params.items() if k2 not in ('api_user','api_key','facility_code')}
            s, d = rgp_get(f'/v1/sales/facility/{fc}', u, k, extra or None)
            send_json(self, s, d)
            return

        # ── Check-ins active now ──────────────────────────────────────────────
        # Nicole confirmed: GET /v1/checkins/active/facility/{facilityCode}
        if path == '/checkins/active':
            s, d = rgp_get(f'/v1/checkins/active/facility/{fc}', u, k)
            if s == 200:
                # Could be a count or a list
                checkins = d.get('checkins', d.get('data', []))
                count = d.get('count', d.get('activeCount', len(checkins) if isinstance(checkins, list) else 0))
                send_json(self, 200, {'active_now': count, 'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat()})
            else:
                send_json(self, s, d)
            return

        # ── Check-ins today ───────────────────────────────────────────────────
        if path == '/checkins/today':
            today = datetime.date.today().isoformat()
            s, d = rgp_get(f'/v1/checkins/facility/{fc}', u, k, {'startDate': today, 'endDate': today})
            if s == 200:
                raw = d.get('checkins', d.get('checkin', d.get('data', [])))
                send_json(self, 200, {'count': len(raw), 'date': today, 'checkins': raw[:500], 'raw_keys': list(d.keys())})
            else:
                send_json(self, s, d)
            return

        # ── Check-ins history ─────────────────────────────────────────────────
        # Nicole confirmed: GET /v1/checkins/facility/{facilityCode} with date range
        if path == '/checkins/history':
            days  = int((params.get('days') or ['30'])[0])
            end   = datetime.date.today()
            start = end - datetime.timedelta(days=days)
            s, d  = rgp_get(f'/v1/checkins/facility/{fc}', u, k, {
                'startDate': start.isoformat(),
                'endDate':   end.isoformat(),
            })
            if s == 200:
                raw = d.get('checkins', d.get('checkin', d.get('data', [])))
                daily = {}; hourly = {}; dow = {0:0,1:0,2:0,3:0,4:0,5:0,6:0}
                for c in raw:
                    # Try every possible date field name
                    ds = str(c.get('checkinDate', c.get('checkin_date', c.get('date', c.get('visitDate', '')))))[:10]
                    if ds and ds != 'N':
                        daily[ds] = daily.get(ds, 0) + 1
                        try:
                            dt = datetime.date.fromisoformat(ds)
                            dow[dt.weekday()] = dow.get(dt.weekday(), 0) + 1
                        except: pass
                    ts = str(c.get('checkinTime', c.get('checkin_time', c.get('time', c.get('visitTime', '')))))
                    if ts and len(ts) >= 2:
                        try:
                            h = int(ts[:2])
                            if 0 <= h <= 23:
                                hourly[h] = hourly.get(h, 0) + 1
                        except: pass
                send_json(self, 200, {
                    'total': len(raw), 'days': days,
                    'start_date': start.isoformat(), 'end_date': end.isoformat(),
                    'daily_counts': daily, 'hourly_distribution': hourly,
                    'day_of_week_counts': dow,
                    'avg_per_day': round(len(raw)/days, 1) if days else 0,
                    'raw_keys': list(d.keys()),
                    'checkins': raw[:1000],
                })
            else:
                send_json(self, s, {'error': d, 'rgp_path': f'/v1/checkins/facility/{fc}'})
            return

        # ── Dashboard — single call for home screen ───────────────────────────
        if path == '/dashboard':
            today    = datetime.date.today().isoformat()
            start_30 = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()

            def safe(fn):
                try:   return fn()
                except: return (500, {})

            s_active, d_active = safe(lambda: rgp_get(f'/v1/checkins/active/facility/{fc}', u, k))
            s_today,  d_today  = safe(lambda: rgp_get(f'/v1/checkins/facility/{fc}', u, k, {'startDate': today, 'endDate': today}))
            s_mem,    d_mem    = safe(lambda: rgp_get(f'/v1/customers/facility/{fc}', u, k, {'pageSize': 1}))
            s_sales,  d_sales  = safe(lambda: rgp_get(f'/v1/sales/facility/{fc}', u, k, {'startDate': start_30, 'endDate': today, 'pageSize': 1}))

            checkins_today = d_today.get('checkins', d_today.get('data', [])) if s_today==200 else []
            members_total  = d_mem.get('total', d_mem.get('totalCount', d_mem.get('count', 0))) if s_mem==200 else 0
            active_now     = d_active.get('count', d_active.get('activeCount', 0)) if s_active==200 else 0
            revenue_total  = d_sales.get('total', d_sales.get('totalCount', 0)) if s_sales==200 else 0

            send_json(self, 200, {
                'active_now':       active_now,
                'checkins_today':   len(checkins_today),
                'members_total':    members_total,
                'revenue_30d':      0,  # populated by /invoices call separately
                'facility_code':    fc,
                'endpoints_working': {
                    'checkins_active': s_active == 200,
                    'checkins_today':  s_today  == 200,
                    'members':         s_mem    == 200,
                    'sales':           s_sales  == 200,
                },
                'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            })
            return

        # ── Discover — test every Nicole-confirmed endpoint ───────────────────
        if path == '/discover':
            results = {}
            tests = [
                ('facilities',        '/v1/facilities',                     {}),
                ('customers',         f'/v1/customers/facility/{fc}',       {'pageSize': 1}),
                ('bookings',          f'/v1/bookings/facility/{fc}',        {'pageSize': 1}),
                ('invoices',          f'/v1/invoices/facility/{fc}',        {'pageSize': 1}),
                ('sales',             f'/v1/sales/facility/{fc}',           {'pageSize': 1}),
                ('checkins',          f'/v1/checkins/facility/{fc}',        {'pageSize': 1}),
                ('checkins_active',   f'/v1/checkins/active/facility/{fc}', {}),
            ]
            for name, ep, p in tests:
                s, d = rgp_get(ep, u, k, p or None)
                list_key = next((kk for kk, vv in d.items() if isinstance(vv, list)), None)
                results[name] = {
                    'endpoint': ep,
                    'status':   s,
                    'working':  s == 200,
                    'has_data': bool(d.get(list_key)) if list_key else s == 200,
                    'keys':     list(d.keys())[:10],
                    'preview':  str(d)[:200],
                }
            all_ok = all(v['working'] for v in results.values())
            send_json(self, 200, {
                'facility_code': fc,
                'all_working':   all_ok,
                'results':       results,
            })
            return

        send_json(self, 404, {'error': f'Unknown endpoint: {path}', 'hint': 'Call /health for available endpoints'})


if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', PORT), ProxyHandler)
    print(f'OperatorOS RGP Proxy v3.1 — port {PORT}')
    print('Ready. Watching for requests...')
    server.serve_forever()
