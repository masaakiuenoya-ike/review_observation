-- 直近の取込日で表示する VIEW（Connected Sheets で値が出ないとき用）
-- 実行: YOUR_DATASET を mart_gbp に置換してから、各文を BigQuery で実行。
-- 例: sed 's/YOUR_DATASET/mart_gbp/g' sql/002b_views_latest_available.sql で置換し、1文ずつ bq query またはコンソールで実行。

-- v_latest_available_ratings（store_name は places_provider_map.display_name）
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

-- v_latest_available_alerts
CREATE OR REPLACE VIEW `YOUR_DATASET.v_latest_available_alerts` AS
WITH base AS (
  SELECT * FROM `YOUR_DATASET.v_latest_available_ratings`
)
SELECT snapshot_date, store_code, store_name, provider, 'low_rating' AS alert_type, rating_value, delta_rating, delta_review_count FROM base WHERE rating_value < 4.2
UNION ALL
SELECT snapshot_date, store_code, store_name, provider, 'rating_drop' AS alert_type, rating_value, delta_rating, delta_review_count FROM base WHERE delta_rating <= -0.2
UNION ALL
SELECT snapshot_date, store_code, store_name, provider, 'review_surge' AS alert_type, rating_value, delta_rating, delta_review_count FROM base WHERE delta_review_count >= 10;
