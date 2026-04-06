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
SHEET_TAB_PERFORMANCE_MONTHLY = os.environ.get(
    "SHEET_TAB_PERFORMANCE_MONTHLY", "Google_Monthly_Performance"
)

# Slack（未設定なら通知スキップ）
SLACK_WEBHOOK_URL = (os.environ.get("SLACK_WEBHOOK_URL") or "").strip()

# Google Maps（Place Details / Geocoding — fetch_gbp_locations の座標補完用。未設定なら GBP の latlng のみ）
GOOGLE_MAPS_API_KEY = (os.environ.get("GOOGLE_MAPS_API_KEY") or "").strip()


# 新規レビュー要約 → Slack（取込直後）。要約は BQ に保存しない。
def _env_bool(name: str, default: bool = False) -> bool:
    v = (os.environ.get(name) or "").strip().lower()
    if v in ("1", "true", "yes", "on"):
        return True
    if v in ("0", "false", "no", "off"):
        return False
    return default


REVIEW_SUMMARY_ENABLED = _env_bool("REVIEW_SUMMARY_ENABLED", False)
# True のとき要約は Vertex AI（Gemini）＋実行 SA の ADC。False のとき従来どおり GEMINI_API_KEY（AI Studio）
REVIEW_SUMMARY_USE_VERTEX_AI = _env_bool("REVIEW_SUMMARY_USE_VERTEX_AI", False)
# True のとき Slack へ POST せず、要約本文をログに出すだけ（Gemini は呼ぶ）
REVIEW_SUMMARY_SLACK_DRY_RUN = _env_bool("REVIEW_SUMMARY_SLACK_DRY_RUN", False)
GEMINI_API_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
# Vertex は Publisher モデル ID（例: gemini-2.0-flash-001）が必要。無印 gemini-2.0-flash は 404 になりやすい。
GEMINI_MODEL = (os.environ.get("GEMINI_MODEL") or "gemini-2.0-flash-001").strip()
# Vertex: プロジェクト未指定時は Cloud Run と同じ GCP_PROJECT_ID
VERTEX_AI_PROJECT = (
    (os.environ.get("VERTEX_AI_PROJECT") or "").strip()
    or (os.environ.get("GCP_PROJECT_ID") or "").strip()
    or "ikeuchi-data-sync"
)
# Vertex のリージョン。Gemini Publisher モデルは global が公式例で、us-central1 だと 404 になるプロジェクトがある。
# 固定リージョンにしたい場合は VERTEX_AI_LOCATION（例: us-central1, asia-northeast1）を環境変数で上書き。
VERTEX_AI_LOCATION = (os.environ.get("VERTEX_AI_LOCATION") or "global").strip()
# 未設定なら SLACK_WEBHOOK_URL を流用（本番とテストで分けたいときだけ設定）
REVIEW_SUMMARY_SLACK_WEBHOOK_URL = (
    os.environ.get("REVIEW_SUMMARY_SLACK_WEBHOOK_URL") or ""
).strip()


# 取込の並列数（店舗ごとの GBP 取得＋BQ MERGE を同時に実行する数）。
# 1 にすると店舗を直列処理し、reviews テーブルへの同時 MERGE 競合を避けやすい。
def _parse_max_workers() -> int:
    v = os.environ.get("MAX_WORKERS", "1").strip()
    try:
        n = int(v)
        return max(1, min(n, 16))
    except ValueError:
        return 1


MAX_WORKERS = _parse_max_workers()
