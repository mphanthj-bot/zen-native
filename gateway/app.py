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


def _socks_conn():
    """HTTPSConnection đi qua SOCKS5 (stdlib thuần, không dep)."""
    import socket as _so
    host, port = SOCKS.rsplit(':', 1)
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
    base = _iface_prefix()
    if not base:
        return
    for i in range(n):
        ip = ':'.join(base) + f'::a17{i}'
        subprocess.run(['sudo', '-n', 'ip', '-6', 'addr', 'add', f'{ip}/64',
                        'dev', os.environ.get('ZEN_V6_IFACE', 'enp3s0')],
                       capture_output=True, timeout=15)
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


def zen_conn():
    kw = {'timeout': 120, 'context': ssl.create_default_context()}
    src = _next_src()
    if src:
        return http.client.HTTPSConnection('opencode.ai', 443,
                                           source_address=(src, 0), **kw)
    return http.client.HTTPSConnection('opencode.ai', 443, **kw)


def zen_post(path, body, via=None):
    headers, _ = zen_headers()
    data = json.dumps(body).encode()
    if via == 'socks':
        conn = _socks_conn()
    else:
        conn = zen_conn()
    conn.request('POST', path, body=data, headers=headers)
    return conn.getresponse()


RETRYABLE = {403, 429, 502, 503}


def zen_post_fallback(path, body):
    """Direct trước, fail retryable thì đổi đường WARP SOCKS 1 lần."""
    try:
        r = zen_post(path, body)
        if r.status not in RETRYABLE:
            return r
        first = r.status
    except Exception:
        first = 'ERR'
    if not SOCKS:
        raise OSError(f'direct failed ({first}), SOCKS fallback tắt')
    return zen_post(path, body, via='socks')


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
                upstream = self._chat(body)
            elif self.path == '/v1/responses':
                upstream = self._resp(body)
            else:
                return self._json(404, {'error': 'not found'})
        except Exception as e:
            return self._json(502, {'error': str(e)[:200]})
        self.send_response(upstream.status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        while True:
            chunk = upstream.read(65536)
            if not chunk:
                break
            self.wfile.write(chunk)

    def _chat(self, body):
        msgs = [m for m in body.get('messages', []) if m.get('role') != 'system']
        out = {
            'model': body.get('model', 'big-pickle'), 'messages': [
                {'role': 'system', 'content': SYSTEM},
                *({'role': m.get('role', 'user'),
                   'content': as_text(m.get('content'))} for m in msgs)],
            'stream': True, 'stream_options': {'include_usage': True}}
        # forward tool-use + sampling params nguyên vẹn (compat tuyệt đối)
        for k in ('tools', 'tool_choice', 'temperature', 'top_p',
                  'max_completion_tokens', 'max_tokens', 'reasoning_effort'):
            if body.get(k) is not None:
                out[k] = body[k]
        return zen_post_fallback('/zen/v1/chat/completions', out)

    def _resp(self, body):
        raw = body.get('input', '')
        text = as_text(raw) if isinstance(raw, (str, list)) else ''
        if not isinstance(raw, list):
            raw = [{'type': 'message', 'role': 'user',
                    'content': [{'type': 'input_text', 'text': text}]}]
        _, sid = zen_headers()
        out = {
            'model': body.get('model', 'muse-spark-1.3-contributor-free'),
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
        return zen_post_fallback('/zen/v1/responses', out)


if __name__ == '__main__':
    if not GW_KEY:
        print('CẢNH BÁO: chưa đặt ZEN_GW_KEY — gateway đang mở không key!')
    srv = http.server.ThreadingHTTPServer((HOST, PORT), Handler)
    print(f'zen-native gateway nghe {HOST}:{PORT}')
    srv.serve_forever()
