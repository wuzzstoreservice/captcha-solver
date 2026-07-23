#!/usr/bin/env bash
# Smoke test against a running captcha-solver instance.
set -euo pipefail
BASE="${1:-http://127.0.0.1:5080}"
URL="${SMOKE_URL:-https://example.com}"
SITEKEY="${SMOKE_SITEKEY:-}"

echo "== health =="
curl -fsS "$BASE/health" | tee /tmp/cs-health.json
echo

if [[ -z "$SITEKEY" ]]; then
  echo "Set SMOKE_SITEKEY to run a real/mock turnstile create+poll."
  echo "Example: SMOKE_SITEKEY=0x4AAAA... $0"
  exit 0
fi

echo "== create legacy turnstile =="
CREATE=$(curl -fsS --get "$BASE/turnstile" \
  --data-urlencode "url=$URL" \
  --data-urlencode "sitekey=$SITEKEY")
echo "$CREATE"
TASK_ID=$(python3 -c "import json,sys; print(json.load(sys.stdin)['taskId'])" <<<"$CREATE")

echo "== poll =="
for i in $(seq 1 90); do
  RES=$(curl -fsS "$BASE/result?id=$TASK_ID")
  echo "[$i] $RES"
  if echo "$RES" | python3 -c 'import json,sys; b=json.load(sys.stdin); sys.exit(0 if b.get("status")=="ready" and b.get("errorId",0)==0 else 1)'; then
    echo "OK"
    exit 0
  fi
  if echo "$RES" | python3 -c 'import json,sys; b=json.load(sys.stdin); sys.exit(0 if b.get("errorId")==1 else 1)'; then
    echo "FAIL"
    exit 1
  fi
  sleep 1
done
echo "TIMEOUT"
exit 1
