# Filter free (động) — cost = 0 mới chuẩn

1. `GET https://opencode.ai/zen/v1/models` live → IDs đang serve (hiện 85).
2. Giao với `https://models.dev/api.json` → `providers.opencode.models` →
   giữ `cost.input == 0 and cost.output == 0`.
3. `jev-1.13-free` giữ bằng rule tên (endpoint systemone riêng,
   không có entry models.dev). jev KHÔNG đưa vào grok/bench (chat/responses
   không ăn systemone) — cố tình loại, không phải sót.

Kết quả 2026-10-02: 13 IDs (12 chat/responses + jev). `muse-spark-1.2`
bị UI ẩn nhưng cost 0 + gọi thật 200 — filter cost bắt được đúng cái UI giấu.
`deepseek/ling` 400 là sai shape request, không phải hết free.
