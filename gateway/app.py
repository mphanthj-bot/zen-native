#!/usr/bin/env python3
"""Gateway riêng: 1 endpoint OpenAI-compatible cho mọi client trong nhà.

Làm đúng recipe đã decode: tự gắn fingerprint + system gốc, forward user
content lên Zen chính chủ. Chỉ dùng thư viện chuẩn Python (chạy tốt Termux).

  ZEN_GW_KEY=key-cua-anh python3 app.py   # nghe 127.0.0.1:8080
Clients trỏ:  baseURL http://127.0.0.1:8080/v1  +  key = ZEN_GW_KEY
"""
import http.client
import http.server
import json
import os
import secrets
import socket
import ssl
import urllib.request
import uuid

HOST = os.environ.get('ZEN_HOST', '127.0.0.1')
PORT = int(os.environ.get('ZEN_PORT', '8080'))
GW_KEY = os.environ.get('ZEN_GW_KEY', '')
SRC_IP = os.environ.get('ZEN_SRC_IP', '') or None
ZEN = 'https://opencode.ai/zen/v1'
HERE = os.path.dirname(os.path.abspath(__file__))
SOCKS = os.environ.get('ZEN_SOCKS', '127.0.0.1:40000')  # '' = tắt fallback


def _socks_conn(addr=None):
    """HTTPSConnection đi qua SOCKS5 addr (stdlib thuần, không dep)."""
    import socket as _so
    host, port = (addr or SOCKS).rsplit(':', 1)
    raw = _so.create_connection((host, int(port)), timeout=30)
    raw.sendall(b'\x05\x01\x00')
    if raw.recv(2) != b'\x05\x00':
        raise OSError('socks5 hello rejected')
    req = b'\x05\x01\x00\x03' + bytes([len('opencode.ai')]) + b'opencode.ai' \
        + (443).to_bytes(2, 'big')
    raw.sendall(req)
    resp = raw.recv(10)
    if len(resp) < 2 or resp[1] != 0x00:
        raise OSError(f'socks5 connect failed: {resp.hex()}')
    ctx = ssl.create_default_context()
    tls = ctx.wrap_socket(raw, server_hostname='opencode.ai')
    conn = http.client.HTTPSConnection('opencode.ai', 443, timeout=120)
    conn.sock = tls
    conn._http_vsn, conn._http_vsn_str = (1, 1), 'HTTP/1.1'
    return conn

# --- Auto xoay IP egress (mỗi request 1 IPv6 trong /64, chia quota) ---
import itertools
import subprocess
import threading

_pool = [None]
_lock = threading.Lock()


def _iface_prefix():
    iface = os.environ.get('ZEN_V6_IFACE', 'enp3s0')
    try:
        out = subprocess.run(['ip', '-6', 'addr', 'show', 'dev', iface],
                             capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            line = line.strip()
            if line.startswith('inet6 240') or line.startswith('inet6 2'):
                return line.split()[1].split('/')[0].split(':')[:4]
    except Exception:
        pass
    return None


def _ensure_pool(n=4):
    import re
    base = _iface_prefix()
    if not base:
        return
    prefix = ':'.join(base) + '::'
    # gom cả IPs pool đã có sẵn trên interface (sống qua restart).
    # chỉ lấy họ a17* (pool xoay), không đụng IP chính của máy.
    try:
        out = subprocess.run(['ip', '-6', 'addr', 'show', 'dev',
                              os.environ.get('ZEN_V6_IFACE', 'enp3s0')],
                             capture_output=True, text=True,
                             timeout=10).stdout
        for m in re.findall(r'inet6\s+([0-9a-f:]+)/64', out):
            if m.startswith(prefix + 'a17') and m not in _pool:
                _pool.append(m)
    except Exception:
        pass
    for i in range(n):
        ip = prefix + f'a17{i}'
        subprocess.run(['sudo', '-n', 'ip', '-6', 'addr', 'add', f'{ip}/64',
                        'dev', os.environ.get('ZEN_V6_IFACE', 'enp3s0')],
                       capture_output=True, timeout=15)
        if ip not in _pool:
            _pool.append(ip)
    global _cycle
    _cycle = itertools.cycle([x for x in _pool if x])


_cycle = None
try:
    _ensure_pool(int(os.environ.get('ZEN_POOL', '4')))
except Exception:
    pass


def _next_src():
    if _cycle is None:
        return SRC_IP
    with _lock:
        return next(_cycle)

with open(os.path.join(HERE, '..', 'recipe', 'system.chat.txt')) as f:
    SYSTEM = f.read()
with open(os.path.join(HERE, '..', 'recipe', 'instructions.resp.txt')) as f:
    INSTRUCTIONS = f.read()

UA = 'opencode/latest/2.0.22/cli'


def zen_headers():
    sid = 'ses_' + secrets.token_hex(13)
    return {'Content-Type': 'application/json', 'Authorization': 'Bearer public',
            'User-Agent': UA, 'x-opencode-client': 'cli',
            'x-opencode-project': uuid.uuid4().hex, 'x-opencode-session': sid,
            'x-opencode-session-id': sid, 'x-session-affinity': sid,
            'x-session-id': sid, 'prompt_cache_key': sid}, sid


def zen_conn(src='__pool__'):
    kw = {'timeout': 120, 'context': ssl.create_default_context()}
    if src == '__pool__':
        src = _next_src()
    if src:
        return http.client.HTTPSConnection('opencode.ai', 443,
                                           source_address=(src, 0), **kw)
    return http.client.HTTPSConnection('opencode.ai', 443, **kw)


def zen_post(path, body, egress=None):
    """egress: None/direct-ip | ('socks', addr)."""
    headers, _ = zen_headers()
    data = json.dumps(body).encode()
    if isinstance(egress, tuple):
        conn = _socks_conn(egress[1])
    else:
        conn = zen_conn(egress)
    conn.request('POST', path, body=data, headers=headers)
    return conn.getresponse()


def _direct_ips():
    """IPs direct hiện có: pool v6 + SRC_IP (nếu đặt)."""
    ips = [x for x in _pool if x]
    if SRC_IP and SRC_IP not in ips:
        ips.append(SRC_IP)
    return ips


RETRYABLE = {403, 429, 502, 503}
MODEL_FAIL = {400, 401, 404}
COOLDOWN = int(os.environ.get('ZEN_COOLDOWN', '180'))

CHAT_FREE = [m for m in (os.environ.get('ZEN_CHAT_ORDER') or
             'space-bunny-free,fledge-alpha-free,big-pickle,mimo-v2.5-free,'
             'mimo-v2.6-flash-free,longcat-2.5-preview-free,'
             'ling-3.0-flash-fin-free,nemotron-3-ultra-free,'
             'nemotron-3.5-lightning-free').split(',') if m]
RESP_FREE = [m for m in (os.environ.get('ZEN_RESP_ORDER') or
             'muse-spark-1.3-contributor-free,muse-spark-1.2-contributor-free'
             ).split(',') if m]

CODE_HINTS = ('def ', 'class ', 'import ', 'function', 'const ', '=>', 'error',
              'traceback', 'bug', 'code', 'python', 'javascript', 'golang',
              'fibonacci', 'def main', 'select ', 'SELECT')


def pick_model(requested, text, resp_mode):
    """AUTO (kiểu webchat) theo prompt + manual fallback chain."""
    pool = list(RESP_FREE) if resp_mode else list(CHAT_FREE)
    if requested and requested != 'auto':
        return [requested] + [m for m in pool if m != requested]
    t = (text or '').lower()
    if resp_mode:
        return pool
    if len(text or '') > 60000:
        first = 'space-bunny-free'
    elif any(h in t for h in CODE_HINTS):
        first = 'big-pickle'
    else:
        first = 'space-bunny-free'
    return [first] + [m for m in pool if m != first]


class EgressPool:
    """Xoay egress + cooldown IP chết, tự hồi."""

    def __init__(self):
        self.cool = {}

    def items(self):
        out = [{'kind': 'direct', 'ip': ip} for ip in _direct_ips()]
        for addr in [a.strip() for a in (SOCKS or '').split(',') if a.strip()]:
            out.append({'kind': 'socks', 'addr': addr})
        return out or [{'kind': 'direct', 'ip': None}]

    def key(self, e):
        return e.get('ip') or e.get('addr') or 'direct'

    def order(self):
        import time as _t
        now = _t.time()
        items = self.items()
        live = [e for e in items if self.cool.get(self.key(e), 0) <= now]
        if live:
            return live
        return sorted(items, key=lambda e: self.cool.get(self.key(e), 0))

    def fail(self, e):
        import time as _t
        self.cool[self.key(e)] = _t.time() + COOLDOWN


EGRESS = EgressPool()


def zen_request(path, body, models):
    """Thử từng model x từng egress. Trả (response, model, egress_key)."""
    import time as _t
    last = OSError('no egress')
    for m in models[:4]:
        body['model'] = m
        for e in EGRESS.order():
            t0 = _t.time()
            try:
                if e['kind'] == 'socks':
                    r = zen_post(path, body, egress=('socks', e['addr']))
                else:
                    r = zen_post(path, body, egress=e['ip'])
            except Exception as ex:
                last = ex
                EGRESS.fail(e)
                print(f'[{_t.strftime("%H:%M:%S")}] FAIL {m} via '
                      f'{EGRESS.key(e)}: {str(ex)[:120]}', flush=True)
                continue
            if r.status == 200:
                return r, m, EGRESS.key(e)
            if r.status in RETRYABLE:
                r.read()
                EGRESS.fail(e)
                last = OSError(f'{r.status} via {EGRESS.key(e)}')
                print(f'[{_t.strftime("%H:%M:%S")}] RETRYABLE {r.status} '
                      f'{m} via {EGRESS.key(e)}', flush=True)
                continue
            r.read()
            last = OSError(f'{r.status} model {m}')
            print(f'[{_t.strftime("%H:%M:%S")}] MODEL-FAIL {r.status} {m}',
                  flush=True)
            break
    raise last


def as_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ''.join(p.get('text', '') for p in content
                        if isinstance(p, dict))
    return str(content or '')


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = 'zen-native/1.0'

    def log_message(self, *a):
        pass

    def _auth(self):
        if not GW_KEY:
            return True
        got = self.headers.get('Authorization', '')
        return got == f'Bearer {GW_KEY}'

    def _json(self, code, obj):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == '/healthz':
            return self._json(200, {'ok': True})
        if self.path == '/v1/models':
            try:
                req = urllib.request.Request(
                    ZEN + '/models',
                    headers={'User-Agent': UA})
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = r.read()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            except Exception as e:
                self._json(502, {'error': str(e)[:200]})
            return
        self._json(404, {'error': 'not found'})

    def do_POST(self):
        if not self._auth():
            return self._json(401, {'error': 'invalid local API key'})
        try:
            body = json.loads(self.rfile.read(
                int(self.headers.get('Content-Length', 0)) or 0) or b'{}')
        except Exception:
            return self._json(400, {'error': 'bad json'})
        try:
            if self.path == '/v1/chat/completions':
                upstream, model, ekey = self._chat(body)
            elif self.path == '/v1/responses':
                upstream, model, ekey = self._resp(body)
            else:
                return self._json(404, {'error': 'not found'})
        except Exception as e:
            return self._json(502, {'error': str(e)[:200]})
        self.send_response(upstream.status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('X-Zen-Model', model)
        self.send_header('X-Zen-Egress', ekey)
        self.end_headers()
        while True:
            chunk = upstream.read(65536)
            if not chunk:
                break
            self.wfile.write(chunk)

    def _chat(self, body):
        msgs = [m for m in body.get('messages', []) if m.get('role') != 'system']
        text = ' '.join(as_text(m.get('content')) for m in msgs)
        out = {
            'messages': [
                {'role': 'system', 'content': SYSTEM},
                *({'role': m.get('role', 'user'),
                   'content': as_text(m.get('content'))} for m in msgs)],
            'stream': True, 'stream_options': {'include_usage': True}}
        # forward tool-use + sampling params nguyên vẹn (compat tuyệt đối)
        for k in ('tools', 'tool_choice', 'temperature', 'top_p',
                  'max_completion_tokens', 'max_tokens', 'reasoning_effort'):
            if body.get(k) is not None:
                out[k] = body[k]
        models = pick_model(body.get('model', 'auto'), text, False)
        return zen_request('/zen/v1/chat/completions', out, models)

    def _resp(self, body):
        raw = body.get('input', '')
        text = as_text(raw) if isinstance(raw, (str, list)) else ''
        if not isinstance(raw, list):
            raw = [{'type': 'message', 'role': 'user',
                    'content': [{'type': 'input_text', 'text': text}]}]
        _, sid = zen_headers()
        out = {
            # BẮT BUỘC system gốc: instructions của client (codex/grok) gửi
            # lên là rớt lane free (đã verify: FreeTierError). Trade-off:
            # model chạy nhưng theo hành vi title-generator.
            'instructions': INSTRUCTIONS, 'input': raw, 'store': False,
            'prompt_cache_key': sid,
            'include': ['reasoning.encrypted_content'], 'stream': True}
        for k in ('tools', 'tool_choice', 'temperature', 'top_p',
                  'max_output_tokens', 'reasoning'):
            if body.get(k) is not None:
                out[k] = body[k]
        models = pick_model(body.get('model', 'auto'), text, True)
        return zen_request('/zen/v1/responses', out, models)


if __name__ == '__main__':
    if not GW_KEY:
        print('CẢNH BÁO: chưa đặt ZEN_GW_KEY — gateway đang mở không key!')
    srv = http.server.ThreadingHTTPServer((HOST, PORT), Handler)
    print(f'zen-native gateway nghe {HOST}:{PORT}')
    srv.serve_forever()
