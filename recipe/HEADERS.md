# HEADERS — fingerprint request genuine (capture từ binary + đối chiếu code gốc)

```
Authorization: Bearer public
User-Agent: opencode/latest/2.0.22/cli        <- theo version opencode đang cài
x-opencode-client: cli
x-opencode-project: <uuid hex tự sinh>
x-opencode-session: ses_<random>               <- 4 header session CÙNG 1 ID
x-opencode-session-id: ses_<random>
x-session-affinity: ses_<random>
x-session-id: ses_<random>
Content-Type: application/json
```

Body chat: `{model, messages: [system GỐC + user tự do], stream: true,
stream_options: {include_usage: true}}`.
Body responses: `{model, instructions: SYSTEM GỐC, input: [typed message],
store: false, prompt_cache_key: <session ID>, include:
["reasoning.encrypted_content"], stream: true}`.

Ràng buộc đã verify: system/instructions giữ nguyên byte gốc
(`recipe/system.chat.txt`, `recipe/instructions.resp.txt`);
`stream: true` bắt buộc; `max_tokens < 16` bị từ chối.
