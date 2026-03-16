-- review_observation VIEW（設計書 rev2 準拠）
-- 適用時: YOUR_DATASET を mart_gbp 等に置換

-- 5.1 v_latest_with_delta_ratings（store_name は places_provider_map.display_name）
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
  COALESCE(p.display_name, '') AS store_name,
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
  ON t.store_code = y.store_code AND t.provider = y.provider
LEFT JOIN `YOUR_DATASET.places_provider_map` p ON t.store_code = p.store_code AND t.provider = p.provider;

-- 5.1b v_latest_available_ratings（直近の取込日で表示。store_name は places_provider_map.display_name）
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
  COALESCE(p.display_name, '') AS store_name,
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
  ON t.store_code = y.store_code AND t.provider = y.provider
LEFT JOIN `YOUR_DATASET.places_provider_map` p ON t.store_code = p.store_code AND t.provider = p.provider;

-- 5.2 v_latest_with_delta_performance（日次）
-- 注意: performance_daily_snapshot には現状どこからも投入していないため、この VIEW は 0 行のまま。
-- 日次パフォーマンス取込ジョブを実装すると更新される。月次データを見たい場合は v_latest_available_performance_monthly を使用。
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
  COALESCE(p.display_name, '') AS store_name,
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
  ON t.store_code = y.store_code AND t.provider = y.provider
LEFT JOIN `YOUR_DATASET.places_provider_map` p ON t.store_code = p.store_code AND t.provider = p.provider;

-- 5.2b v_latest_available_performance_monthly（月次・直近月＋前月比。store_name は places_provider_map.display_name）
CREATE OR REPLACE VIEW `YOUR_DATASET.v_latest_available_performance_monthly` AS
WITH max_month AS (
  SELECT MAX(snapshot_month) AS m FROM `YOUR_DATASET.performance_monthly_snapshot`
),
this_month AS (
  SELECT r.* FROM `YOUR_DATASET.performance_monthly_snapshot` r
  INNER JOIN max_month mm ON r.snapshot_month = mm.m
),
prev_month AS (
  SELECT r.* FROM `YOUR_DATASET.performance_monthly_snapshot` r
  INNER JOIN max_month mm ON r.snapshot_month = DATE_SUB(mm.m, INTERVAL 1 MONTH)
)
SELECT
  t.snapshot_month AS snapshot_date,
  t.store_code,
  COALESCE(p.display_name, '') AS store_name,
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
FROM this_month t
LEFT JOIN prev_month y
  ON t.store_code = y.store_code AND t.provider = y.provider
LEFT JOIN `YOUR_DATASET.places_provider_map` p ON t.store_code = p.store_code AND t.provider = p.provider;

-- 5.3 v_rating_alerts（閾値 SQL 固定: 4.2 / -0.2 / 10）
CREATE OR REPLACE VIEW `YOUR_DATASET.v_rating_alerts` AS
WITH base AS (
  SELECT * FROM `YOUR_DATASET.v_latest_with_delta_ratings`
)
SELECT
  snapshot_date,
  store_code,
  store_name,
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
  store_name,
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
  store_name,
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
SELECT snapshot_date, store_code, store_name, provider, 'low_rating' AS alert_type, rating_value, delta_rating, delta_review_count FROM base WHERE rating_value < 4.2
UNION ALL
SELECT snapshot_date, store_code, store_name, provider, 'rating_drop' AS alert_type, rating_value, delta_rating, delta_review_count FROM base WHERE delta_rating <= -0.2
UNION ALL
SELECT snapshot_date, store_code, store_name, provider, 'review_surge' AS alert_type, rating_value, delta_rating, delta_review_count FROM base WHERE delta_review_count >= 10;
