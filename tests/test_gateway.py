#!/usr/bin/env python3
"""Test runtime e2e cho gateway (stdlib, không dep).
Chạy:  ZEN_GW_KEY=... python3 tests/test_gateway.py
Yêu cầu gateway đang chạy ở 127.0.0.1:8080.
"""
import json
import os
import unittest
import urllib.request
import urllib.error

BASE = 'http://127.0.0.1:8080'
KEY = os.environ.get('ZEN_GW_KEY', '')


def call(method, path, body=None, key=None):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={'Content-Type': 'application/json',
                 'Authorization': f'Bearer {key if key is not None else KEY}'},
        method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


class GatewayE2E(unittest.TestCase):
    def test_health(self):
        st, _, body = call('GET', '/healthz')
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(body), {'ok': True})

    def test_auth_required(self):
        st, _, _ = call('POST', '/v1/chat/completions', {}, key='sai-key')
        self.assertEqual(st, 401)

    def test_models_list_live(self):
        st, _, body = call('GET', '/v1/models')
        self.assertEqual(st, 200)
        ids = [m['id'] for m in json.loads(body).get('data', [])]
        self.assertIn('big-pickle', ids)
        self.assertGreater(len(ids), 50)

    def test_chat_small(self):
        st, headers, body = call('POST', '/v1/chat/completions', {
            'model': 'space-bunny-free',
            'messages': [{'role': 'user', 'content': 'hi'}]})
        self.assertEqual(st, 200, body[:200])
        self.assertIn('X-Zen-Model', headers)
        text = body.decode('utf-8', 'replace')
        self.assertIn('chat.completion.chunk', text)

    def test_manual_fallback(self):
        st, headers, _ = call('POST', '/v1/chat/completions', {
            'model': 'khong-ton-tai',
            'messages': [{'role': 'user', 'content': 'hi'}]})
        self.assertEqual(st, 200)
        self.assertNotEqual(headers.get('X-Zen-Model'), 'khong-ton-tai')

    def test_auto_routing(self):
        st, headers, _ = call('POST', '/v1/chat/completions', {
            'model': 'auto',
            'messages': [{'role': 'user', 'content': 'write python fib'}]})
        self.assertEqual(st, 200)
        self.assertEqual(headers.get('X-Zen-Model'), 'big-pickle')

    def test_responses_small(self):
        st, headers, body = call('POST', '/v1/responses', {
            'model': 'muse-spark-1.3-contributor-free',
            'input': [{'role': 'user', 'content': 'hi'}]})
        self.assertEqual(st, 200, body[:200])
        text = body.decode('utf-8', 'replace')
        self.assertIn('response.', text)


if __name__ == '__main__':
    if not KEY:
        raise SystemExit('Thiếu ZEN_GW_KEY')
    unittest.main(verbosity=2)
