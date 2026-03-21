#!/usr/bin/env bash
# 本日分の日次サマリを手動実行する。
# GET /health を 200 が返るまでポーリングしてから POST /daily-summary を実行する。
#
# 前提: gcloud auth login 済み。手動実行するユーザーに Cloud Run の run.invoker が必要。
#   付与: gcloud run services add-iam-policy-binding review-observation --region=asia-northeast1 \
#         --member="user:$(gcloud config get-value account)" --role="roles/run.invoker"
# 使い方: bash scripts/run_daily_summary_manual.sh

set -e
REGION="${REGION:-asia-northeast1}"
SERVICE_NAME="${SERVICE_NAME:-review-observation}"
POLL_TIMEOUT="${POLL_TIMEOUT:-30}"   # 1回の curl のタイムアウト（秒）
POLL_INTERVAL="${POLL_INTERVAL:-10}" # リトライ間隔（秒）
POLL_MAX="${POLL_MAX:-60}"           # 最大ポーリング回数（30s×60=30分）
DAILY_TIMEOUT="${DAILY_TIMEOUT:-600}" # POST /daily-summary のタイムアウト（秒）

echo "=============================================="
echo "本日分 日次サマリ手動実行（ポーリング付き）"
echo "=============================================="

URL=$(gcloud run services describe "${SERVICE_NAME}" --region="${REGION}" --format='value(status.url)')
echo "URL: $URL"

# 認証: 過去の成功例では手元で「--audiences なし」で 200 が返っている。
# 環境によっては --audiences が必要なため、両方試す（なし優先）。
TOKEN=
if TOKEN=$(gcloud auth print-identity-token 2>/dev/null); then
  echo "トークン取得: print-identity-token（audiences なし）"
fi
if [ -z "$TOKEN" ] && TOKEN=$(gcloud auth print-identity-token --audiences="$URL" 2>/dev/null); then
  echo "トークン取得: print-identity-token --audiences=URL"
fi
if [ -z "$TOKEN" ]; then
  echo "ERROR: トークン取得に失敗しました。gcloud auth login を実行し、run.invoker を付与してください。"
  exit 1
fi
echo "トークン取得 OK"
echo ""

echo "--- GET /health を 200 が返るまでポーリング（1回 ${POLL_TIMEOUT}s タイムアウト、${POLL_INTERVAL}s 間隔、最大 ${POLL_MAX} 回）---"
for i in $(seq 1 "$POLL_MAX"); do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$POLL_TIMEOUT" -H "Authorization: Bearer $TOKEN" "$URL/health" 2>/dev/null || echo "000")
  echo "  試行 $i: HTTP $CODE"
  if [ "$CODE" = "200" ]; then
    echo "  → 200 取得。POST /daily-summary を実行します。"
    break
  fi
  if [ "$i" -eq "$POLL_MAX" ]; then
    echo "ERROR: ${POLL_MAX} 回試行しても 200 が返りませんでした。"
    exit 1
  fi
  sleep "$POLL_INTERVAL"
done
echo ""

echo "--- POST /daily-summary（タイムアウト ${DAILY_TIMEOUT}s）---"
RESP=$(curl -s -w "\nHTTP_CODE:%{http_code}" --max-time "$DAILY_TIMEOUT" -X POST \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{}' "$URL/daily-summary" 2>/dev/null) || true
HTTP_CODE=$(echo "$RESP" | grep "HTTP_CODE:" | sed 's/HTTP_CODE://')
BODY=$(echo "$RESP" | sed '/HTTP_CODE:/d')
echo "$BODY"
echo "HTTP: $HTTP_CODE"
echo ""

if [ "$HTTP_CODE" = "200" ]; then
  echo "完了: 日次サマリを Slack に送信しました。"
else
  echo "WARN: HTTP $HTTP_CODE。Slack に届いていない可能性があります。"
  exit 1
fi
