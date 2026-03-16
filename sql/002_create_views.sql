-- review_observation VIEW（設計書 rev2 準拠）
-- 適用時: YOUR_DATASET を mart_gbp 等に置換

-- 5.1 v_latest_with_delta_ratings
CREATE OR REPLACE VIEW `YOUR_DATASET.v_latest_with_delta_ratings` AS
WITH today AS (
  SELECT * FROM `YOUR_DATASET.ratings_daily_snapshot`
  WHERE snapshot_date = CURRENT_DATE('Asia/Tokyo')
),
yesterday AS (
  SELECT * FROM `YOUR_DATASET.ratings_daily_snapshot`
  WHERE snapshot_date = DATE_SUB(CURRENT_DATE('Asia/Tokyo'), INTERVAL 1 DAY)
)
SELECT
  t.snapshot_date,
  t.store_code,
  t.provider,
  t.provider_place_id,
  t.rating_value,
  t.review_count,
  t.fetched_at,
  t.ingest_run_id,
  t.status,
  t.rating_value - y.rating_value AS delta_rating,
  t.review_count - y.review_count AS delta_review_count
FROM today t
LEFT JOIN yesterday y
  ON t.store_code = y.store_code AND t.provider = y.provider;

-- 5.1b v_latest_available_ratings（直近の取込日で表示。Connected Sheets で値が出ないとき用）
-- 「今日」の取込が無くても、最後に取込があった日を「今日」として表示する。
CREATE OR REPLACE VIEW `YOUR_DATASET.v_latest_available_ratings` AS
WITH max_date AS (
  SELECT MAX(snapshot_date) AS d FROM `YOUR_DATASET.ratings_daily_snapshot`
),
today AS (
  SELECT r.* FROM `YOUR_DATASET.ratings_daily_snapshot` r
  INNER JOIN max_date m ON r.snapshot_date = m.d
),
yesterday AS (
  SELECT r.* FROM `YOUR_DATASET.ratings_daily_snapshot` r
  INNER JOIN max_date m ON r.snapshot_date = DATE_SUB(m.d, INTERVAL 1 DAY)
)
SELECT
  t.snapshot_date,
  t.store_code,
  t.provider,
  t.provider_place_id,
  t.rating_value,
  t.review_count,
  t.fetched_at,
  t.ingest_run_id,
  t.status,
  t.rating_value - y.rating_value AS delta_rating,
  t.review_count - y.review_count AS delta_review_count
FROM today t
LEFT JOIN yesterday y
  ON t.store_code = y.store_code AND t.provider = y.provider;

-- 5.2 v_latest_with_delta_performance
CREATE OR REPLACE VIEW `YOUR_DATASET.v_latest_with_delta_performance` AS
WITH today AS (
  SELECT * FROM `YOUR_DATASET.performance_daily_snapshot`
  WHERE snapshot_date = CURRENT_DATE('Asia/Tokyo')
),
yesterday AS (
  SELECT * FROM `YOUR_DATASET.performance_daily_snapshot`
  WHERE snapshot_date = DATE_SUB(CURRENT_DATE('Asia/Tokyo'), INTERVAL 1 DAY)
)
SELECT
  t.snapshot_date,
  t.store_code,
  t.provider,
  t.provider_place_id,
  t.impressions,
  t.calls,
  t.direction_requests,
  t.website_clicks,
  t.fetched_at,
  t.ingest_run_id,
  t.status,
  t.impressions - IFNULL(y.impressions, 0) AS delta_impressions,
  t.calls - IFNULL(y.calls, 0) AS delta_calls,
  t.direction_requests - IFNULL(y.direction_requests, 0) AS delta_direction_requests,
  t.website_clicks - IFNULL(y.website_clicks, 0) AS delta_website_clicks
FROM today t
LEFT JOIN yesterday y
  ON t.store_code = y.store_code AND t.provider = y.provider;

-- 5.3 v_rating_alerts（閾値 SQL 固定: 4.2 / -0.2 / 10）
CREATE OR REPLACE VIEW `YOUR_DATASET.v_rating_alerts` AS
WITH base AS (
  SELECT * FROM `YOUR_DATASET.v_latest_with_delta_ratings`
)
SELECT
  snapshot_date,
  store_code,
  provider,
  'low_rating' AS alert_type,
  rating_value,
  delta_rating,
  delta_review_count
FROM base
WHERE rating_value < 4.2
UNION ALL
SELECT
  snapshot_date,
  store_code,
  provider,
  'rating_drop' AS alert_type,
  rating_value,
  delta_rating,
  delta_review_count
FROM base
WHERE delta_rating <= -0.2
UNION ALL
SELECT
  snapshot_date,
  store_code,
  provider,
  'review_surge' AS alert_type,
  rating_value,
  delta_rating,
  delta_review_count
FROM base
WHERE delta_review_count >= 10;

-- 5.3b v_latest_available_alerts（直近の取込日ベースのアラート。Connected Sheets 用）
CREATE OR REPLACE VIEW `YOUR_DATASET.v_latest_available_alerts` AS
WITH base AS (
  SELECT * FROM `YOUR_DATASET.v_latest_available_ratings`
)
SELECT snapshot_date, store_code, provider, 'low_rating' AS alert_type, rating_value, delta_rating, delta_review_count FROM base WHERE rating_value < 4.2
UNION ALL
SELECT snapshot_date, store_code, provider, 'rating_drop' AS alert_type, rating_value, delta_rating, delta_review_count FROM base WHERE delta_rating <= -0.2
UNION ALL
SELECT snapshot_date, store_code, provider, 'review_surge' AS alert_type, rating_value, delta_rating, delta_review_count FROM base WHERE delta_review_count >= 10;
