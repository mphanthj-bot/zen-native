#!/usr/bin/env python3
"""Benchmark Zen free models via genuine native endpoints (no gateway).
Formula: Bearer public + opencode fingerprint headers + KNOWN harness
system/instructions + free user content. Source IP pinned for clean bucket.
Usage: python3 bench_zen_free.py [--only idx] [--list]
"""
import http.client, ssl, json, secrets, uuid, time, sys

SRC = '2405:4802:1d13:e0::a17c'
HOST = 'opencode.ai'
PROMPT = 'reply with exactly: ok'

CHAT_MODELS = ['big-pickle', 'deepseek-v4-flash-free', 'fledge-alpha-free',
  'ling-3.0-flash-fin-free', 'longcat-2.5-preview-free', 'mimo-v2.5-free',
  'mimo-v2.6-flash-free', 'nemotron-3-ultra-free', 'nemotron-3.5-lightning-free',
  'space-bunny-free']
RESP_MODELS = ['muse-spark-1.2-contributor-free', 'muse-spark-1.3-contributor-free']

def base_headers():
    sid = 'ses_' + secrets.token_hex(13)
    return {'Content-Type': 'application/json', 'Authorization': 'Bearer public',
        'User-Agent': 'opencode/latest/2.0.22/cli', 'x-opencode-client': 'cli',
        'x-opencode-project': uuid.uuid4().hex, 'x-opencode-session': sid,
        'x-opencode-session-id': sid, 'x-session-affinity': sid, 'x-session-id': sid}

def load_flow(path, small=True):
    from mitmproxy.io import FlowReader
    from mitmproxy.http import HTTPFlow
    with open(path, 'rb') as f:
        for flow in FlowReader(f).stream():
            if isinstance(flow, HTTPFlow) and flow.request.method == 'POST':
                b = json.loads(flow.request.content)
                if (len(flow.request.content) < 10000) == small:
                    return b
    raise RuntimeError('flow not found in ' + path)

def post(path, body):
    conn = http.client.HTTPSConnection(HOST, 443, source_address=(SRC, 0),
        timeout=90, context=ssl.create_default_context())
    conn.request('POST', path, body=json.dumps(body).encode(), headers=base_headers())
    r = conn.getresponse()
    t0 = time.time()
    chunks = []
    first_byte = None
    while True:
        ch = r.read(4096)
        if first_byte is None:
            first_byte = time.time() - t0
        if not ch:
            break
        chunks.append(ch)
    return r.status, time.time() - t0, first_byte or 0.0, b''.join(chunks).decode('utf-8', 'replace')

def parse_chat_sse(text):
    out = []
    for line in text.splitlines():
        if line.startswith('data: ') and line[6:].strip() not in ('[DONE]', ''):
            try:
                d = json.loads(line[6:])
                c = d.get('choices', [{}])[0]
                t = (c.get('delta', {}) or {}).get('content') or (c.get('message', {}) or {}).get('content')
                if t:
                    out.append(t)
            except Exception:
                pass
    return ''.join(out)

def parse_resp_sse(text):
    out = []
    for line in text.splitlines():
        if line.startswith('data: '):
            try:
                d = json.loads(line[6:])
                if d.get('type') == 'response.output_text.delta':
                    out.append(d.get('delta', ''))
            except Exception:
                pass
    return ''.join(out)

def live_free_list():
    conn = http.client.HTTPSConnection(HOST, 443, source_address=(SRC, 0),
        timeout=30, context=ssl.create_default_context())
    conn.request('GET', '/zen/v1/models')
    data = json.loads(conn.getresponse().read())
    ids = sorted(m['id'] for m in data.get('data', []))
    return [i for i in ids if 'free' in i.lower() or i == 'big-pickle']

def bench_chat(model, tpl):
    body = {'model': model,
        'messages': [{'role': 'system', 'content': tpl['messages'][0]['content']},
                     {'role': 'user', 'content': PROMPT}],
        'stream': True, 'stream_options': {'include_usage': True}}
    st, total, first, text = post('/zen/v1/chat/completions', body)
    return st, total, first, parse_chat_sse(text)[:100]

def bench_resp(model, tpl):
    body = dict(tpl)
    body['model'] = model
    body['input'] = [{'role': 'user', 'content': PROMPT}]
    body['stream'] = True
    st, total, first, text = post('/zen/v1/responses', body)
    return st, total, first, parse_resp_sse(text)[:100]

def main():
    if '--list' in sys.argv:
        ids = live_free_list()
        print(f'LIVE FREE COUNT: {len(ids)}')
        for i in ids:
            print(' ', i)
        return
    only = None
    if '--only' in sys.argv:
        only = sys.argv[sys.argv.index('--only') + 1]
    chat_tpl = load_flow('/tmp/opencode/mitm/flows.bin', True)
    resp_tpl = load_flow('/tmp/opencode/mitm/flows_resp.bin', True)
    jobs = [('chat', m) for m in CHAT_MODELS] + [('resp', m) for m in RESP_MODELS]
    if only:
        jobs = [j for j in jobs if only in j[1]]
    print(f'{len(jobs)} models, ~15s spacing')
    results = []
    for i, (kind, m) in enumerate(jobs):
        try:
            fn = bench_chat if kind == 'chat' else bench_resp
            tpl = chat_tpl if kind == 'chat' else resp_tpl
            st, total, first, txt = fn(m, tpl)
            line = f'[{i+1}/{len(jobs)}] {kind:4} {m:38} {st} {total:5.1f}s first:{first:4.1f}s reply:{txt[:60]!r}'
        except Exception as e:
            line = f'[{i+1}/{len(jobs)}] {kind:4} {m:38} ERR {str(e)[:80]}'
        print(line, flush=True)
        results.append(line)
        if i < len(jobs) - 1:
            time.sleep(15)
    print('DONE')

if __name__ == '__main__':
    main()
