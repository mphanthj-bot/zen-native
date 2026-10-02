# Grok CLI (bản build xai, native Responses) vào Zen.
# grok-build-0.1 serve ở endpoint responses chính chủ:
#   baseURL = https://opencode.ai/zen/v1/responses
#   model   = grok-build-0.1
# Auth + fingerprint headers y công thức chuẩn (Bearer public,
# User-Agent opencode/..., x-opencode-client: cli).
# Nếu CLI không cho custom headers, trỏ nó vào gateway/ của repo này:
#   baseURL = http://127.0.0.1:8080/v1  +  key = ZEN_GW_KEY
