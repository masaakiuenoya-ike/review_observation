"""環境変数ベースの設定。Cloud Run では --set-env-vars で注入。"""

import os

# BigQuery
BQ_PROJECT = os.environ.get("BQ_PROJECT", "ikeuchi-ga4")
BQ_DATASET = os.environ.get("BQ_DATASET", "mart_gbp")
BQ_LOCATION = os.environ.get("BQ_LOCATION", "asia-northeast1")

# GBP OAuth（Secret Manager の Secret 名。中身は JSON: client_id, client_secret, refresh_token）
GBP_OAUTH_SECRET_NAME = os.environ.get(
    "GBP_OAUTH_SECRET_NAME",
    "projects/ikeuchi-data-sync/secrets/gbp-oauth-json/versions/latest",
)

# GCP プロジェクト（Secret Manager / Cloud Run はこちら）
GCP_PROJECT = os.environ.get("GCP_PROJECT_ID", "ikeuchi-data-sync")

# Google Sheets（未設定なら Sheets 更新はスキップ）
SHEET_ID = (os.environ.get("SHEET_ID") or "").strip()
SHEET_TAB_LATEST = os.environ.get("SHEET_TAB_LATEST", "LATEST")
SHEET_TAB_ALERT = os.environ.get("SHEET_TAB_ALERT", "ALERT")
SHEET_TAB_SUMMARY = os.environ.get("SHEET_TAB_SUMMARY", "サマリ")

# Slack（未設定なら通知スキップ）
SLACK_WEBHOOK_URL = (os.environ.get("SLACK_WEBHOOK_URL") or "").strip()


# 取込の並列数（店舗ごとの GBP 取得＋BQ MERGE を同時に実行する数）。デフォルト 5。
def _parse_max_workers() -> int:
    v = os.environ.get("MAX_WORKERS", "5").strip()
    try:
        n = int(v)
        return max(1, min(n, 16))
    except ValueError:
        return 5


MAX_WORKERS = _parse_max_workers()
