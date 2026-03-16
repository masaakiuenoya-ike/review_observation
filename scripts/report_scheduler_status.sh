#!/usr/bin/env bash
# Cloud Scheduler（review_observation）の実行状態を報告用に出力する。
# 事前に gcloud auth login で認証しておく。
# 使い方: ./scripts/report_scheduler_status.sh  または  bash scripts/report_scheduler_status.sh

set -e
PROJECT="${GCP_PROJECT_ID:-ikeuchi-data-sync}"
REGION="${REGION:-asia-northeast1}"

echo "=============================================="
echo "review_observation Cloud Scheduler 実行状態報告"
echo "プロジェクト: ${PROJECT}  リージョン: ${REGION}"
echo "取得日時: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "=============================================="
echo ""

echo "--- ジョブ一覧（review_observation のみ） ---"
gcloud scheduler jobs list --project="${PROJECT}" --location="${REGION}" \
  --format="table(name.basename(), schedule, state, lastAttemptTime)" \
  --filter="name:review-observation" 2>/dev/null || true
echo ""

for job in review-observation-hourly review-observation-daily review-observation-monthly; do
  if gcloud scheduler jobs describe "${job}" --project="${PROJECT}" --location="${REGION}" &>/dev/null; then
    echo "--- ${job} 詳細 ---"
    gcloud scheduler jobs describe "${job}" --project="${PROJECT}" --location="${REGION}" \
      --format="yaml(schedule, state, lastAttemptTime, status)" 2>/dev/null || true
    echo ""
  fi
done

echo "--- 直近実行ログ（review-observation-hourly） ---"
gcloud logging read \
  'resource.type="cloud_scheduler_job" resource.labels.job_id="review-observation-hourly"' \
  --project="${PROJECT}" --limit=10 \
  --format="table(timestamp.date('%Y-%m-%d %H:%M:%S'), severity, textPayload)" 2>/dev/null || true
echo ""
echo "=============================================="
echo "報告 End"
