"""
OperatorOS RGP Proxy v3.1
Credentials load from rgp_proxy_config.json automatically.
Just run this file — no setup needed.
"""
import json, urllib.request, urllib.parse, base64, os, datetime, ssl
from http.server import HTTPServer, BaseHTTPRequestHandler

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rgp_proxy_config.json')

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except:
        return {}

CORS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
}

def send_json(handler, code, body):
    data = json.dumps(body, default=str).encode()
    handler.send_response(code)
    for k, v in CORS.items():
        handler.send_header(k, v)
    handler.send_header('Content-Type', 'application/json')
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

class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        ts = datetime.datetime.now().strftime('%H:%M:%S')
        print(f'[{ts}] {self.path[:80]}')

    def do_OPTIONS(self):
        self.send_response(200)
        for k, v in CORS.items(): self.send_header(k, v)
        self.end_headers()

    def get_creds(self, params):
        cfg = load_config()
        u  = (params.get('api_user') or [None])[0] or cfg.get('rgp_user', '')
        k  = (params.get('api_key')  or [None])[0] or cfg.get('rgp_key',  '')
        fc = (params.get('facility_code') or [None])[0] or cfg.get('facility_code', 'ASP')
        return u.strip(), k.strip(), fc.strip()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        path   = parsed.path

        if path == '/health':
            send_json(self, 200, {'status': 'ok', 'version': '3.1', 'service': 'OperatorOS RGP Proxy'})
            return

        # WHEN I WORK — proxied to avoid browser CORS blocks
        if path == '/wiw/shifts':
            email    = (params.get('email') or [None])[0]
            password = (params.get('password') or [None])[0]
            days     = int((params.get('days') or ['21'])[0])
            if not email or not password:
                send_json(self, 401, {'error': 'Missing WIW email or password'})
                return
            try:
                login_req = urllib.request.Request(
                    'https://api.login.wheniwork.com/login',
                    data=json.dumps({'email': email, 'password': password}).encode(),
                    headers={'Content-Type': 'application/json', 'W-Key': 'knowledgebase'},
                    method='POST'
                )
                ctx = ssl.create_default_context()
                with urllib.request.urlopen(login_req, timeout=15, context=ctx) as resp:
                    login_data = json.loads(resp.read().decode())
                token = login_data.get('token') or (login_data.get('login') or {}).get('token')
                if not token:
                    send_json(self, 401, {'error': 'WIW login failed', 'detail': login_data})
                    return

                start = datetime.date.today().isoformat()
                end   = (datetime.date.today() + datetime.timedelta(days=days)).isoformat()
                shifts_req = urllib.request.Request(
                    f'https://api.wheniwork.com/2/shifts?start={start}&end={end}',
                    headers={'W-Token': token}
                )
                with urllib.request.urlopen(shifts_req, timeout=15, context=ctx) as resp2:
                    shifts_data = json.loads(resp2.read().decode())
                send_json(self, 200, {'shifts': shifts_data.get('shifts', []), 'total': len(shifts_data.get('shifts', []))})
            except urllib.error.HTTPError as e:
                send_json(self, e.code, {'error': 'WIW request failed', 'detail': e.read().decode()[:300]})
            except Exception as e:
                send_json(self, 500, {'error': 'WIW proxy error', 'detail': str(e)})
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

        # INVOICES — Nicole confirmed: /v1/invoices/facility/{facilityCode}
        if path == '/invoices':
            today    = datetime.date.today().isoformat()
            start_30 = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
            s, d = rgp_get(f'/v1/invoices/facility/{fc}', u, k, {
                'startDate': start_30,
                'endDate':   today,
                'orderBy':   'invoicePostDate',
                'orderDir':  'desc',
                'pageSize':  500,
            })
            if s == 200:
                raw = d.get('invoices', d.get('invoice', d.get('data', [])))
                # Filter out voided invoices for accurate revenue
                valid = [i for i in raw if not i.get('voidedInvoice', 0)]
                total_rev = sum(float(i.get('amount', 0) or 0) for i in valid)
                # Normalize to clean schema using confirmed field names
                invoices = [{
                    'date':    i.get('invoicePostDate', ''),
                    'type':    i.get('invtype', ''),
                    'amount':  float(i.get('amount', 0) or 0),
                    'tax':     float(i.get('salesTax', 0) or 0),
                    'source':  (i.get('payment') or {}).get('source', ''),
                    'voided':  bool(i.get('voidedInvoice', 0)),
                    'memo':    i.get('memo', ''),
                    'items':   i.get('items', []),
                } for i in raw]
                send_json(self, 200, {
                    'invoices': invoices,
                    'total': len(invoices),
                    'valid_count': len(valid),
                    'total_revenue': round(total_rev, 2),
                    'raw_keys': list(d.keys()),
                })
            else:
                send_json(self, s, {'error': d, 'path_tried': f'/v1/invoices/facility/{fc}'})
            return

        # CHECKINS ACTIVE — Nicole confirmed: /v1/checkins/active/facility/{facilityCode}
        if path == '/checkins/active':
            s, d = rgp_get(f'/v1/checkins/active/facility/{fc}', u, k)
            if s == 200:
                checkins = d.get('checkins', d.get('data', []))
                count = d.get('count', d.get('activeCount', len(checkins) if isinstance(checkins, list) else 0))
                send_json(self, 200, {'active_now': count})
            else:
                send_json(self, s, d)
            return

        # CHECKINS TODAY
        if path == '/checkins/today':
            today_str = datetime.date.today().isoformat()
            start_ts = today_str + ' 00:00:00'
            end_ts   = today_str + ' 23:59:59'
            s, d = rgp_get(f'/v1/checkins/facility/{fc}', u, k, {'startDate': start_ts, 'endDate': end_ts})
            if s == 200:
                raw = d.get('checkins', d.get('checkin', d.get('data', [])))
                send_json(self, 200, {'count': len(raw), 'date': today, 'checkins': raw[:500], 'raw_keys': list(d.keys())})
            else:
                send_json(self, s, d)
            return

        # CHECKINS HISTORY — Nicole confirmed: /v1/checkins/facility/{facilityCode} with date range
        if path == '/checkins/history':
            days  = int((params.get('days') or ['30'])[0])
            end   = datetime.date.today()
            start = end - datetime.timedelta(days=days)
            start_ts = start.isoformat() + ' 00:00:00'
            end_ts   = end.isoformat() + ' 23:59:59'
            s, d  = rgp_get(f'/v1/checkins/facility/{fc}', u, k, {'startDate': start_ts, 'endDate': end_ts})
            if s == 200:
                raw = d.get('checkins', d.get('checkin', d.get('data', [])))
                daily = {}; hourly = {}; dow = {0:0,1:0,2:0,3:0,4:0,5:0,6:0}
                for c in raw:
                    ds = str(c.get('checkinDate', c.get('checkin_date', c.get('date', c.get('visitDate', '')))))[:10]
                    if ds and len(ds) == 10:
                        daily[ds] = daily.get(ds, 0) + 1
                        try:
                            dt = datetime.date.fromisoformat(ds)
                            dow[dt.weekday()] = dow.get(dt.weekday(), 0) + 1
                        except: pass
                    ts = str(c.get('checkinTime', c.get('checkin_time', c.get('time', ''))))
                    if ts and len(ts) >= 2:
                        try:
                            h = int(ts[:2])
                            if 0 <= h <= 23: hourly[h] = hourly.get(h, 0) + 1
                        except: pass
                send_json(self, 200, {
                    'total': len(raw), 'days': days,
                    'daily_counts': daily, 'hourly_distribution': hourly,
                    'day_of_week_counts': dow,
                    'avg_per_day': round(len(raw)/days, 1) if days else 0,
                    'raw_keys': list(d.keys()),
                })
            else:
                send_json(self, s, {'error': d, 'path_tried': f'/v1/checkins/facility/{fc}'})
            return

        # DASHBOARD — single call for home screen numbers
        if path == '/dashboard':
            today    = datetime.date.today().isoformat()
            start_30 = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
            today_start_ts = today + ' 00:00:00'
            today_end_ts   = today + ' 23:59:59'
            def safe(fn):
                try:   return fn()
                except: return (500, {})
            s1,d1 = safe(lambda: rgp_get(f'/v1/checkins/active/facility/{fc}', u, k))
            s2,d2 = safe(lambda: rgp_get(f'/v1/checkins/facility/{fc}', u, k, {'startDate': today_start_ts, 'endDate': today_end_ts}))
            s3,d3 = safe(lambda: rgp_get(f'/v1/customers/facility/{fc}', u, k, {'pageSize': 1}))
            s4,d4 = safe(lambda: rgp_get(f'/v1/invoices/facility/{fc}', u, k, {'startDate': start_30, 'endDate': today, 'pageSize': 1}))
            active_now   = d1.get('count', 0) if s1==200 else 0
            today_list   = d2.get('checkins', d2.get('data', [])) if s2==200 else []
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
                ('checkins',        f'/v1/checkins/facility/{fc}',       {'pageSize':1, 'startDate': (datetime.date.today()-datetime.timedelta(days=7)).isoformat(), 'endDate': datetime.date.today().isoformat()}),
                ('checkins_active', f'/v1/checkins/active/facility/{fc}',{'startDate': datetime.date.today().isoformat(), 'endDate': datetime.date.today().isoformat()}),
            ]
            results = {}
            for name, ep, p in tests:
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
    server = HTTPServer(('0.0.0.0', port), Handler)
    print('OperatorOS RGP Proxy v3.1')
    print(f'Running on port {port}')
    print('Credentials loaded from rgp_proxy_config.json')
    print('Keep this window open while using OperatorOS.')
    print('---')
    server.serve_forever()
