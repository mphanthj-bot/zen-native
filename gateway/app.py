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
    if SRC_IP:
        return http.client.HTTPSConnection('opencode.ai', 443,
                                           source_address=(SRC_IP, 0), **kw)
    return http.client.HTTPSConnection('opencode.ai', 443, **kw)


def zen_post(path, body):
    headers, _ = zen_headers()
    conn = zen_conn()
    conn.request('POST', path, body=json.dumps(body).encode(), headers=headers)
    return conn.getresponse()


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
        return zen_post('/zen/v1/chat/completions', {
            'model': body.get('model', 'big-pickle'), 'messages': [
                {'role': 'system', 'content': SYSTEM},
                *({'role': m.get('role', 'user'),
                   'content': as_text(m.get('content'))} for m in msgs)],
            'stream': True, 'stream_options': {'include_usage': True}})

    def _resp(self, body):
        raw = body.get('input', '')
        text = as_text(raw) if isinstance(raw, (str, list)) else ''
        if not isinstance(raw, list):
            raw = [{'type': 'message', 'role': 'user',
                    'content': [{'type': 'input_text', 'text': text}]}]
        _, sid = zen_headers()
        return zen_post('/zen/v1/responses', {
            'model': body.get('model', 'muse-spark-1.3-contributor-free'),
            'instructions': INSTRUCTIONS, 'input': raw, 'store': False,
            'prompt_cache_key': sid,
            'include': ['reasoning.encrypted_content'], 'stream': True})


if __name__ == '__main__':
    if not GW_KEY:
        print('CẢNH BÁO: chưa đặt ZEN_GW_KEY — gateway đang mở không key!')
    srv = http.server.ThreadingHTTPServer((HOST, PORT), Handler)
    print(f'zen-native gateway nghe {HOST}:{PORT}')
    srv.serve_forever()
