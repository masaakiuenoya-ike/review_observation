-- review_observation SSOT テーブル（設計書 rev2 準拠）
-- 適用時: YOUR_DATASET を mart_gbp 等に置換

-- 3.1 places_provider_map
CREATE TABLE IF NOT EXISTS `YOUR_DATASET.places_provider_map` (
  store_code STRING NOT NULL,
  provider STRING NOT NULL,
  provider_place_id STRING NOT NULL,
  provider_account_id STRING,
  display_name STRING,
  is_active BOOL NOT NULL,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
)
OPTIONS(description = "store_code とプロバイダ側店舗識別子の対応表");

-- 3.2 ratings_daily_snapshot
CREATE TABLE IF NOT EXISTS `YOUR_DATASET.ratings_daily_snapshot` (
  snapshot_date DATE NOT NULL,
  store_code STRING NOT NULL,
  store_name STRING,
  provider STRING NOT NULL,
  provider_place_id STRING,
  rating_value FLOAT64,
  review_count INT64,
  fetched_at TIMESTAMP,
  ingest_run_id STRING,
  status STRING,
  error_code STRING,
  error_message STRING
)
PARTITION BY snapshot_date
CLUSTER BY store_code, provider
OPTIONS(description = "レビュー評価の日次スナップショット");

-- 3.3 reviews
CREATE TABLE IF NOT EXISTS `YOUR_DATASET.reviews` (
  store_code STRING NOT NULL,
  store_name STRING,
  provider STRING NOT NULL,
  provider_place_id STRING,
  provider_review_id STRING NOT NULL,
  rating FLOAT64,
  review_text STRING,
  review_created_at TIMESTAMP,
  review_updated_at TIMESTAMP,
  reviewer_display_name STRING,
  ingested_at TIMESTAMP,
  ingest_run_id STRING
)
PARTITION BY DATE(ingested_at)
CLUSTER BY store_code, provider
OPTIONS(description = "レビュー明細");

-- 3.4 raw_provider_payloads
CREATE TABLE IF NOT EXISTS `YOUR_DATASET.raw_provider_payloads` (
  ingest_run_id STRING,
  snapshot_date DATE NOT NULL,
  store_code STRING NOT NULL,
  provider STRING NOT NULL,
  endpoint STRING,
  payload JSON,
  created_at TIMESTAMP,
  status STRING,
  error_code STRING,
  error_message STRING
)
PARTITION BY snapshot_date
CLUSTER BY store_code, provider, endpoint
OPTIONS(description = "生レスポンス保管");

-- 4.1 performance_daily_snapshot
CREATE TABLE IF NOT EXISTS `YOUR_DATASET.performance_daily_snapshot` (
  snapshot_date DATE NOT NULL,
  store_code STRING NOT NULL,
  provider STRING NOT NULL,
  provider_place_id STRING,
  impressions INT64,
  calls INT64,
  direction_requests INT64,
  website_clicks INT64,
  fetched_at TIMESTAMP,
  ingest_run_id STRING,
  status STRING,
  error_code STRING,
  error_message STRING
)
PARTITION BY snapshot_date
CLUSTER BY store_code, provider
OPTIONS(description = "GBP パフォーマンス日次スナップショット");

-- 4.2 performance_monthly_snapshot
CREATE TABLE IF NOT EXISTS `YOUR_DATASET.performance_monthly_snapshot` (
  snapshot_month DATE NOT NULL,
  store_code STRING NOT NULL,
  provider STRING NOT NULL,
  provider_place_id STRING,
  impressions INT64,
  calls INT64,
  direction_requests INT64,
  website_clicks INT64,
  fetched_at TIMESTAMP,
  ingest_run_id STRING,
  status STRING,
  error_code STRING,
  error_message STRING
)
PARTITION BY snapshot_month
CLUSTER BY store_code, provider
OPTIONS(description = "GBP パフォーマンス月次スナップショット");
