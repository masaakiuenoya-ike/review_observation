#!/usr/bin/env bash
# review_observation の CLI 診断（要約・環境変数・直近ログ・BQ サンプル）
# 使い方: bash scripts/diag_review_observation_cli.sh
# 前提: gcloud / bq が認証済み（ikeuchi-data-sync / ikeuchi-ga4）

set -euo pipefail
PROJECT_RUN="ikeuchi-data-sync"
REGION="asia-northeast1"
SERVICE="review-observation"
PROJECT_BQ="ikeuchi-ga4"
DATASET_BQ="mart_gbp"

echo "=== 1) review_summary 行（直近3日）==="
gcloud logging read \
  "resource.type=\"cloud_run_revision\" resource.labels.service_name=\"${SERVICE}\" textPayload=~\"review_summary=\"" \
  --project="${PROJECT_RUN}" \
  --limit=25 \
  --format="table(timestamp,textPayload)" \
  --freshness=3d || true

echo ""
echo "=== 2) [review_summary] 詳細（直近3日）==="
gcloud logging read \
  "resource.type=\"cloud_run_revision\" resource.labels.service_name=\"${SERVICE}\" textPayload=~\"\\[review_summary\\]\"" \
  --project="${PROJECT_RUN}" \
  --limit=20 \
  --format="table(timestamp,textPayload)" \
  --freshness=3d || true

echo ""
echo "=== 3) POST / started（直近1日）==="
gcloud logging read \
  "resource.type=\"cloud_run_revision\" resource.labels.service_name=\"${SERVICE}\" textPayload=~\"POST / started\"" \
  --project="${PROJECT_RUN}" \
  --limit=10 \
  --format="table(timestamp,textPayload)" \
  --freshness=1d || true

echo ""
echo "=== 4) Cloud Run 環境変数（要約・Slack・Gemini/Vertex）==="
gcloud run services describe "${SERVICE}" \
  --region="${REGION}" \
  --project="${PROJECT_RUN}" \
  --format=json \
  | python3 -c "
import json, sys
d = json.load(sys.stdin)
for e in d['spec']['template']['spec']['containers'][0].get('env', []):
    n = e.get('name', '')
    if any(x in n for x in ('REVIEW_SUMMARY', 'GEMINI', 'VERTEX', 'SLACK')):
        print(n, '=', e.get('value', '(unset)'))
"

echo ""
echo "=== 5) BQ reviews 直近20件（ingested_at）==="
bq query --project_id="${PROJECT_BQ}" --use_legacy_sql=false --format=pretty "
SELECT store_code, provider_review_id, review_created_at, ingested_at, ingest_run_id
FROM \`${PROJECT_BQ}.${DATASET_BQ}.reviews\`
WHERE provider = 'google'
ORDER BY ingested_at DESC
LIMIT 20
" || true

echo ""
echo "=== 6) BQ performance_monthly 上位10（最新月）==="
bq query --project_id="${PROJECT_BQ}" --use_legacy_sql=false --format=pretty "
SELECT store_code, impressions, calls, direction_requests, website_clicks, snapshot_month, status
FROM \`${PROJECT_BQ}.${DATASET_BQ}.performance_monthly_snapshot\`
WHERE snapshot_month = (SELECT MAX(snapshot_month) FROM \`${PROJECT_BQ}.${DATASET_BQ}.performance_monthly_snapshot\`)
ORDER BY impressions DESC
LIMIT 10
" || true

echo ""
echo "=== 完了（Scheduler 手動実行する場合）==="
echo "gcloud scheduler jobs run review-observation-hourly --location=${REGION} --project=${PROJECT_RUN}"
