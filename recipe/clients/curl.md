# Công thức curl trực tiếp (đã verify 200 live)

## List models (không auth)
curl -s https://opencode.ai/zen/v1/models | python3 -c "import json,sys; print('\n'.join(sorted(m['id'] for m in json.load(sys.stdin)['data'])))"

## Chat model free
SID="ses_$(openssl rand -hex 13)"
curl -s -N -X POST https://opencode.ai/zen/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer public" \
  -H "User-Agent: opencode/latest/2.0.22/cli" \
  -H "x-opencode-client: cli" \
  -H "x-opencode-project: $(uuidgen | tr -d -)" \
  -H "x-opencode-session: $SID" -H "x-opencode-session-id: $SID" \
  -H "x-session-affinity: $SID" -H "x-session-id: $SID" \
  -d "$(python3 -c "import json; print(json.dumps({'model':'big-pickle','messages':[{'role':'system','content':open('../system.chat.txt').read()},{'role':'user','content':'Hi'}],'stream':True,'stream_options':{'include_usage':True}}))")"

## Responses model free (muse-spark-*-contributor-free)
# Body theo recipe/HEADERS.md (instructions = file instructions.resp.txt).
# BẮT BUỘC stream:true — stream:false trả 403.
