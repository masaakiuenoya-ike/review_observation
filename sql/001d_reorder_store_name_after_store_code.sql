-- 既存テーブルの列順を変更: store_name を store_code の直後（右隣）に表示されるようにする。
-- ADD COLUMN で追加したため store_name が末尾にある場合に実行。YOUR_DATASET を mart_gbp に置換。
-- 注意: 必ず 1 文ずつ実行し、各文のジョブが DONE になってから次を実行すること。
--       reviews の再作成時は、DROP reviews_new は「CREATE TABLE reviews AS SELECT * FROM reviews_new」が完了してから実行すること。

-- === ratings_daily_snapshot ===
CREATE TABLE `YOUR_DATASET.ratings_daily_snapshot_new`
PARTITION BY snapshot_date
CLUSTER BY store_code, provider
AS SELECT
  snapshot_date,
  store_code,
  store_name,
  provider,
  provider_place_id,
  rating_value,
  review_count,
  fetched_at,
  ingest_run_id,
  status,
  error_code,
  error_message
FROM `YOUR_DATASET.ratings_daily_snapshot`;

DROP TABLE `YOUR_DATASET.ratings_daily_snapshot`;

CREATE TABLE `YOUR_DATASET.ratings_daily_snapshot`
PARTITION BY snapshot_date
CLUSTER BY store_code, provider
AS SELECT * FROM `YOUR_DATASET.ratings_daily_snapshot_new`;

DROP TABLE `YOUR_DATASET.ratings_daily_snapshot_new`;

-- === reviews ===
CREATE TABLE `YOUR_DATASET.reviews_new`
PARTITION BY DATE(ingested_at)
CLUSTER BY store_code, provider
AS SELECT
  store_code,
  store_name,
  provider,
  provider_place_id,
  provider_review_id,
  rating,
  review_text,
  review_created_at,
  review_updated_at,
  reviewer_display_name,
  ingested_at,
  ingest_run_id
FROM `YOUR_DATASET.reviews`;

DROP TABLE `YOUR_DATASET.reviews`;

CREATE TABLE `YOUR_DATASET.reviews`
PARTITION BY DATE(ingested_at)
CLUSTER BY store_code, provider
AS SELECT * FROM `YOUR_DATASET.reviews_new`;

DROP TABLE `YOUR_DATASET.reviews_new`;
