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
