# zen-native

Đường chính chủ duy nhất tới OpenCode Zen free models — no login, no key signup,
no gateway thứ ba. Mọi client nói OpenAI-compatible đều đấu thẳng vào đây.

## Công thức chuẩn (đã verify live)

Base: `https://opencode.ai/zen/v1` + headers:

```
Authorization: Bearer public
User-Agent: opencode/latest/2.0.22/cli
x-opencode-client: cli
x-opencode-project: <uuid hex tự sinh>
x-opencode-session / -session-id / x-session-affinity / x-session-id: ses_<random>
```

- Chat models → `POST /chat/completions`,
  body `{model, messages: [system GỐC + user tự do], stream: true,
  stream_options: {include_usage: true}}`
- Responses models (`muse-spark-*-contributor-free`, `grok-build-0.1`,
  `gpt-5.x-codex`) → `POST /responses`,
  body `{model, instructions: SYSTEM GỐC, input: [...typed...], store: false,
  prompt_cache_key: <session ID>, include: ["reasoning.encrypted_content"],
  stream: true}`
- List live: `GET /v1/models` (không auth, hiện tại 85 models)
- Ràng buộc: giữ nguyên system/instructions gốc (`recipe/*.txt`),
  `stream: true` bắt buộc, `max_tokens < 16` bị từ chối,
  `429` đợi thử lại, `400` là sai shape với model đó

## Dùng nhanh

```bash
# 1. Xem list free live
python3 tools/bench_zen_free.py --list
# 2. Benchmark toàn bộ free models
python3 tools/bench_zen_free.py
# 3. Chạy gateway local (clients trỏ vào http://127.0.0.1:8080/v1)
ZEN_GW_KEY=doi-key-cua-anh python3 gateway/app.py
```

Client khác (codex/grok/cline/vscode extension): xem `recipe/clients/`.

## Cấu trúc

```
recipe/          công thức + system gốc + config mẫu từng client
  system.chat.txt, instructions.resp.txt
  clients/       codex.config.toml, grok.json, opencode.json, curl.md
gateway/         gateway riêng (~120 dòng, chỉ dùng thư viện chuẩn Python)
tools/           bench_zen_free.py — discovery live + benchmark
MODELS.md        bảng benchmark + filter cost=0
```

## Filter free (động, không hardcode)

1. `GET /v1/models` live → IDs đang serve
2. Giao với `models.dev` → giữ `cost.input == 0 and cost.output == 0`
   (`jev-1.13-free` giữ bằng rule tên — endpoint systemone riêng)

## Benchmark 2026-10-02 (trực tiếp, native)

| Model | KQ | Tổng | Byte đầu |
|---|---|---|---|
| big-pickle | 200 | 4.5s | 2.1s |
| fledge-alpha-free | 200 | 2.7s | 0.7s |
| mimo-v2.5-free | 200 | 2.9s | 0.7s |
| space-bunny-free | 200 | 1.0s | 0.5s |
| mimo-v2.6-flash-free | 200 | 11.5s | 10.4s |
| nemotron-3-ultra-free | 200 | 12s | 5.9s |
| nemotron-3.5-lightning-free | 200 | 376s | 79s |
| muse-spark-1.2-contributor-free (responses) | 200 | 13.8s | — |
| muse-spark-1.3-contributor-free (responses) | 200 | 9.2s | — |
| deepseek-v4-flash-free | 400 | sai shape, retry sau | — |
| ling-3.0-flash-fin-free | 400 | sai shape, retry sau | — |
| longcat-2.5-preview-free | 429 | rate-limit lúc test | — |

## Vận hành egress (khi bị rate-limit)

- Gateway tự xoay IPv6 pool mỗi request (`ZEN_POOL`, `ZEN_V6_IFACE`),
  fail 403/429/502/503 thì đổi đường WARP SOCKS 1 lần (`ZEN_SOCKS`,
  rỗng = tắt fallback).
- WARP proxy mode: `warp-cli mode proxy` + `warp-cli proxy port 40000`
  + `warp-cli connect`. Đổi identity mới: `warp-cli tunnel rotate-keys`.
- Kiểm tra: `curl --socks5-hostname 127.0.0.1:40000 https://ifconfig.me`
