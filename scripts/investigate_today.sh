#!/usr/bin/env bash
# 今日分の動作調査: Scheduler 実行・BQ 直近取込・Cloud Run ログ
# 事前に gcloud auth login で認証しておく。
# 使い方: bash scripts/investigate_today.sh

set -e
PROJECT="${GCP_PROJECT_ID:-ikeuchi-data-sync}"
REGION="${REGION:-asia-northeast1}"
BQ_PROJECT="${BQ_PROJECT:-ikeuchi-ga4}"

echo "=============================================="
echo "今日分 動作調査（review_observation）"
echo "実行日時: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "=============================================="
echo ""

echo "--- 1. Scheduler ジョブ（直近実行・ステータスコード） ---"
echo "code 0=成功, 4=DEADLINE_EXCEEDED, 2=UNKNOWN など"
gcloud scheduler jobs list --project="${PROJECT}" --location="${REGION}" \
  --format="table(name.basename(), schedule, state, lastAttemptTime, status.code)" \
  --filter="name:review-observation" 2>/dev/null || true
echo ""

echo "--- 2. BQ 直近取込日（ratings_daily_snapshot） ---"
bq query --project_id="${BQ_PROJECT}" --use_legacy_sql=false --format=pretty \
  "SELECT snapshot_date, COUNT(*) AS store_count FROM \`${BQ_PROJECT}.mart_gbp.ratings_daily_snapshot\` GROUP BY snapshot_date ORDER BY snapshot_date DESC LIMIT 5" 2>/dev/null || true
echo ""

echo "--- 3. Cloud Run に届いたリクエスト（直近24h） ---"
gcloud logging read \
  'resource.type="cloud_run_revision" resource.labels.service_name="review-observation" httpRequest.requestUrl!=""' \
  --project="${PROJECT}" --limit=25 \
  --format="table(timestamp, httpRequest.requestMethod, httpRequest.requestUrl, httpRequest.status)" \
  --freshness=24h 2>/dev/null || true
echo ""

echo "--- 4. daily-slack の直近実行ログ（Scheduler） ---"
gcloud logging read \
  'resource.type="cloud_scheduler_job" resource.labels.job_id="review-observation-daily-slack"' \
  --project="${PROJECT}" --limit=5 \
  --format="table(timestamp, severity, jsonPayload.status)" \
  --freshness=48h 2>/dev/null || true
echo ""

echo "--- 5. hourly の直近実行ログ（Scheduler） ---"
gcloud logging read \
  'resource.type="cloud_scheduler_job" resource.labels.job_id="review-observation-hourly"' \
  --project="${PROJECT}" --limit=5 \
  --format="table(timestamp, severity, jsonPayload.status)" \
  --freshness=24h 2>/dev/null || true
echo ""

echo "=============================================="
echo "調査 End"
echo "今日の日付に snapshot_date が無い場合: 取込（hourly/daily）が動いていないか 504 で完了していない可能性。"
echo "daily-slack の status.code が 4: Scheduler がタイムアウト。09:10 のウォームアップ（§10.4c）の追加を検討。"
