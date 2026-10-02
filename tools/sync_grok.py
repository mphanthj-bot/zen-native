#!/usr/bin/env python3
"""Tự động sync models Zen free vào grok config. Không hardcode list.
Chạy:  python3 sync_grok.py           # dry-run, chỉ hiện diff
        python3 sync_grok.py --apply   # ghi thật vào ~/.grok/config.toml
"""
import json
import re
import sys
import urllib.request

GROK = '/home/mrkent/.grok/config.toml'
BASE = 'http://127.0.0.1:8080/v1'
ENV = 'OPENCODE2API_KEY'
# Endpoint responses (bảng docs chính chủ). Còn lại mặc định chat.
RESP = {'muse-spark-1.2-contributor-free', 'muse-spark-1.3-contributor-free'}
BEGIN, END = '# >>> zen-native >>>', '# <<< zen-native <<<'


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': 'opencode/latest/2.0.22/cli'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def free_models():
    # jev-1.13-free cố tình loại: endpoint systemone riêng, grok/chat không ăn.
    BLOCKED = {'jev-1.13-free'}
    live = {m['id'] for m in get('https://opencode.ai/zen/v1/models').get('data', [])}
    dev = get('https://models.dev/api.json')['opencode']['models']
    out = {}
    for mid in sorted(live - BLOCKED):
        m = dev.get(mid)
        if m and (m.get('cost') or {}).get('input', 1) == 0 \
                and (m.get('cost') or {}).get('output', 1) == 0:
            out[mid] = m
    return out


def block(mid, m):
    lim = m.get('limit') or {}
    backend = 'responses' if mid in RESP else 'chat_completions'
    q = lambda s: f'"{s}"' if re.match(r'^[A-Za-z0-9_.-]+$', s) else f'"{s}"'
    return (f'[model.{q(mid)}]\nmodel = "{mid}"\nbase_url = "{BASE}"\n'
            f'name = "Zen {mid} (auto-sync)"\n'
            f'description = "OpenCode Zen free, cost 0, auto-sync {__import__("datetime").date.today()}"\n'
            f'env_key = "{ENV}"\napi_backend = "{backend}"\n'
            f'context_window = {lim.get("context", 200000)}\n'
            f'max_completion_tokens = {lim.get("output", 32000)}\n')


def main():
    models = free_models()
    print(f'free live: {len(models)}')
    body = '\n'.join(block(m, models[m]) for m in models)
    new_section = f'{BEGIN}\n{body}{END}\n'
    s = open(GROK).read()
    if BEGIN in s:
        s = re.sub(re.escape(BEGIN) + r'.*?' + re.escape(END) + r'\n?', new_section,
                   s, flags=re.S)
    else:
        # gỡ các block zen viết tay cũ (tránh trùng section)
        legacy = set(models) | {'opencode-muse-1.3'} | {'zen-' + m for m in models}
        parts = re.split(r'(?m)^(?=\[model\.)', s)
        kept = []
        for p in parts:
            m = re.match(r'\[model\.("?)([^"\]]+)\1\]', p)
            if m and m.group(2) in legacy:
                continue
            kept.append(p)
        s = ''.join(kept).rstrip() + '\n\n' + new_section
    # sync allowed_models: giữ entries không phải zen, thay entries zen
    def repl(mo):
        keep = [x for x in re.findall(r'"([^"]+)"', mo.group(0))
                if not x.startswith('zen-') and x != 'opencode-muse-1.3'
                and x not in models]
        return 'allowed_models = [\n' + ''.join(f'    "{x}",\n' for x in keep) \
            + ''.join(f'    "{x}",\n' for x in models) + ']'
    s = re.sub(r'allowed_models = \[.*?\]', repl, s, flags=re.S)
    if '--apply' not in sys.argv:
        print('--- dry-run (them --apply de ghi) ---')
        print(new_section[:600], '...')
        return
    open(GROK, 'w').write(s)
    print('da ghi', GROK)


if __name__ == '__main__':
    main()
